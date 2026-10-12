#define WIN32_LEAN_AND_MEAN
#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#include <windows.h>
#include <bcrypt.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>

/* Exact retail 2.1.5B image. Original files are never patched on disk. */
static const unsigned char retail_sha256[32] = {
    0x94,0x99,0x08,0x64,0xab,0x1d,0xb2,0xdd,0xbe,0x26,0x52,0xcf,0xdb,0xca,0x72,0x63,
    0x56,0xb1,0x9d,0xd3,0xfb,0x75,0x97,0x94,0x5e,0x29,0x7a,0x43,0x97,0x3d,0x99,0xd4
};

static int verify_exe(const wchar_t *path) {
    HANDLE file = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, 0, NULL);
    if (file == INVALID_HANDLE_VALUE) return 0;
    BCRYPT_ALG_HANDLE algorithm = NULL;
    BCRYPT_HASH_HANDLE hash = NULL;
    unsigned char buffer[65536], digest[32];
    DWORD count = 0;
    int ok = BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, NULL, 0) == 0;
    if (ok) ok = BCryptCreateHash(algorithm, &hash, NULL, 0, NULL, 0, 0) == 0;
    while (ok) {
        if (!ReadFile(file, buffer, sizeof(buffer), &count, NULL)) { ok = 0; break; }
        if (!count) break;
        ok = BCryptHashData(hash, buffer, count, 0) == 0;
    }
    if (ok) ok = BCryptFinishHash(hash, digest, sizeof(digest), 0) == 0
                 && memcmp(digest, retail_sha256, sizeof(digest)) == 0;
    if (hash) BCryptDestroyHash(hash);
    if (algorithm) BCryptCloseAlgorithmProvider(algorithm, 0);
    CloseHandle(file);
    return ok;
}

static int read_memory(HANDLE process, uintptr_t address, void *out, size_t size) {
    SIZE_T actual = 0;
    return ReadProcessMemory(process, (LPCVOID)address, out, size, &actual) && actual == size;
}

static int patch(HANDLE process, uintptr_t address, const void *expected,
                 const void *replacement, size_t size) {
    unsigned char before[64], after[64];
    DWORD protection, ignored;
    SIZE_T written = 0;
    if (size > sizeof(before) || !read_memory(process,address,before,size)
        || memcmp(before,expected,size)) return 0;
    if (!VirtualProtectEx(process,(LPVOID)address,size,PAGE_EXECUTE_READWRITE,&protection)) return 0;
    int ok = WriteProcessMemory(process,(LPVOID)address,replacement,size,&written) && written == size;
    ok = VirtualProtectEx(process,(LPVOID)address,size,protection,&ignored) && ok;
    ok = FlushInstructionCache(process,(LPCVOID)address,size) && ok;
    return ok && read_memory(process,address,after,size) && !memcmp(after,replacement,size);
}

static void put32(unsigned char *buffer, size_t *pos, uint32_t value) {
    memcpy(buffer + *pos, &value, 4); *pos += 4;
}

static int hook(HANDLE process, uintptr_t address, const unsigned char *original,
                size_t overwritten, unsigned char *code, size_t size, uintptr_t resume) {
    uintptr_t remote = (uintptr_t)VirtualAllocEx(process,NULL,4096,MEM_RESERVE|MEM_COMMIT,PAGE_READWRITE);
    if (!remote) return 0;
    if (resume) {
        code[size++]=0xe9;
        uint32_t displacement=(uint32_t)(resume-(remote+size+4));
        put32(code,&size,displacement);
    }
    SIZE_T written = 0;
    DWORD ignored;
    if (!WriteProcessMemory(process,(LPVOID)remote,code,size,&written) || written!=size
        || !VirtualProtectEx(process,(LPVOID)remote,4096,PAGE_EXECUTE_READ,&ignored)
        || !FlushInstructionCache(process,(LPCVOID)remote,size)) return 0;
    unsigned char branch[64]; memset(branch,0x90,sizeof(branch));
    branch[0]=0xe9;
    uint32_t offset=(uint32_t)(remote-address-5);
    memcpy(branch+1,&offset,4);
    return patch(process,address,original,branch,overwritten);
}

static int fix_projection(HANDLE process, int width, int height) {
    /* The stock world pane is 640x360, with 120 pixels reserved for the cockpit.
       Keep its vertical FOV; preview and radar panes retain their own projection. */
    static const unsigned char original[15] = {
        0xde,0xc9,0xde,0xc9,0xdd,0x1d,0xd8,0x65,0x5e,0x00,0xe8,0x5c,0xff,0xff,0xff
    };
    unsigned char code[80] = {0xde,0xc9,0xde,0xc9,0x3b,0x05,0x7c,0x56,0x5f,0x00,0x75,0x0b,0x68};
    float ratio=(640.0f*(height-120))/(360.0f*width);
    size_t n=13;
    memcpy(code+n,&ratio,4); n+=4;
    const unsigned char tail[]={0xd8,0x0c,0x24,0x83,0xc4,0x04,
        0xdd,0x1d,0xd8,0x65,0x5e,0x00,0xb8,0x80,0x82,0x42,0x00,0xff,0xd0};
    memcpy(code+n,tail,sizeof(tail)); n+=sizeof(tail);
    return hook(process,0x00428315,original,sizeof(original),code,n,0x00428324);
}

static void emit_offset(unsigned char *code, size_t *n, int x, int y, int root) {
    code[(*n)++]=0x9c; code[(*n)++]=0x60; /* preserve flags and registers */
    if (root) { code[(*n)++]=0xa1; put32(code,n,0x005f56ac); }
    code[(*n)++]=0x81; code[(*n)++]=0x40; code[(*n)++]=0x10; put32(code,n,(uint32_t)x);
    code[(*n)++]=0x81; code[(*n)++]=0x40; code[(*n)++]=0x14; put32(code,n,(uint32_t)y);
    const unsigned char tail[]={0x8b,0x50,0x0c,0x0f,0xaf,0x50,0x14,0x03,0x50,0x10,
        0x89,0x50,0x18,0x61,0x9d};
    memcpy(code+*n,tail,sizeof(tail)); *n+=sizeof(tail);
}

static int fix_ui(HANDLE process, int width, int height) {
    /* Keep the original 640x480 UI canvas, centered horizontally and bottom
       aligned. Apply the same translation to its preview panes and input. */
    int x=(width-640)/2, y=height-480;
    unsigned char code[128]; size_t n=0;
    static const unsigned char root_tail[]={0x5d,0x5b,0x59,0xc3,0x8d,0x49,0x00};
    emit_offset(code,&n,x,y,1);
    memcpy(code+n,root_tail,4); n+=4;
    if (!hook(process,0x0045ecd5,root_tail,sizeof(root_tail),code,n,0)) return 0;

    static const struct {
        uintptr_t address;
        unsigned char size;
        unsigned char original[9];
    } panes[]={
        {0x0045e92c,9,{0x89,0x58,0x18,0x89,0x50,0x20,0x89,0x48,0x28}},
        {0x0045e9b7,6,{0x89,0x50,0x20,0x89,0x48,0x28}},
        {0x0045ea77,6,{0x89,0x50,0x20,0x89,0x48,0x28}},
        {0x0045ea10,7,{0xc7,0x40,0x28,0x64,0x00,0x00,0x00}}
    };
    for (size_t i=0;i<sizeof(panes)/sizeof(panes[0]);++i) {
        n=panes[i].size; memcpy(code,panes[i].original,n);
        emit_offset(code,&n,x,y,0);
        if (!hook(process,panes[i].address,panes[i].original,panes[i].size,
                  code,n,panes[i].address+panes[i].size)) return 0;
    }
    static const unsigned char mouse_original[]={0xc6,0x45,0xf3,0x00,0x8b,0x0d,0xac,0x56,0x5f,0x00};
    const unsigned char mouse_x[]={0x8b,0x4d,0xf8,0x81,0xe9};
    memcpy(code,mouse_x,sizeof(mouse_x)); n=sizeof(mouse_x); put32(code,&n,(uint32_t)x);
    code[n++]=0x89; code[n++]=0x0d; put32(code,&n,0x00677d18);
    const unsigned char mouse_y[]={0x8b,0x55,0xfc,0x81,0xea};
    memcpy(code+n,mouse_y,sizeof(mouse_y)); n+=sizeof(mouse_y); put32(code,&n,(uint32_t)y);
    code[n++]=0x89; code[n++]=0x15; put32(code,&n,0x00677104);
    return hook(process,0x004b89ee,mouse_original,sizeof(mouse_original),code,n,0x004b8a7b);
}

static int patch_display(HANDLE process, int width, int height) {
    const int old_width=640, old_height=480;
    const int old_scene[2]={640,360}, scene[2]={width,height-120};
    const int old_radar[2]={3,346}, radar[2]={3+(width-640)/2,height-134};
    const int old_secondary[2]={533,366}, secondary[2]={533+(width-640)/2,height-114};
    return patch(process,0x004a8137,&old_width,&width,4)
        && patch(process,0x004a813e,&old_height,&height,4)
        && patch(process,0x00577a20,old_scene,scene,8)
        && patch(process,0x00577a40,old_radar,radar,8)
        && patch(process,0x00577a80,old_secondary,secondary,8)
        && fix_projection(process,width,height)
        && fix_ui(process,width,height);
}

int wmain(int argc, wchar_t **argv) {
    if (argc != 2 && argc != 4 && argc != 5) {
        fwprintf(stderr,L"Usage: wulfram-display.exe CLIENT_DIRECTORY [WIDTH HEIGHT [SERVER]]\n");
        return 2;
    }
    SetProcessDPIAware();
    long physical_width=GetSystemMetrics(SM_CXSCREEN), physical_height=GetSystemMetrics(SM_CYSCREEN);
    if (argc >= 4) {
        wchar_t *end_width, *end_height;
        physical_width=wcstol(argv[2],&end_width,10); physical_height=wcstol(argv[3],&end_height,10);
        if (*end_width || *end_height) return 2;
    }
    if (physical_width<800 || physical_width>7680
        || physical_height<600 || physical_height>4320) return 2;
    int ui_scale=(int)(physical_height+719)/720;
    while (ui_scale>1 && (physical_height/ui_scale<480 || physical_width%ui_scale || physical_height%ui_scale)) --ui_scale;
    int width=(int)physical_width/ui_scale, height=(int)physical_height/ui_scale;
    const wchar_t *server=argc==5 ? argv[4] : L"wulfram.canadaverse.org";
    if (!*server || wcslen(server)>253 || wcsspn(server,L"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-")!=wcslen(server)) return 2;
    wchar_t folder[MAX_PATH], executable[MAX_PATH], command[1024];
    DWORD length=GetFullPathNameW(argv[1],MAX_PATH,folder,NULL);
    if (!length || length>MAX_PATH-20) return 2;
    swprintf(executable,MAX_PATH,L"%ls\\wulfram2.exe",folder);
    if (!verify_exe(executable)) { fputs("Unsupported Wulfram executable. No process started.\n",stderr); return 2; }
    swprintf(command,1024,L"\"%ls\" -root -server %ls",executable,server);
    STARTUPINFOW startup = {0}; startup.cb=sizeof(startup);
    PROCESS_INFORMATION child={0};
    if (!CreateProcessW(executable,command,NULL,NULL,FALSE,CREATE_SUSPENDED,NULL,folder,&startup,&child)) {
        fprintf(stderr,"Launch failed: %lu\n",GetLastError()); return 1;
    }
    if (!patch_display(child.hProcess,width,height) || ResumeThread(child.hThread)==(DWORD)-1) {
        fprintf(stderr,"Display signatures/write failed; stopping only the new suspended child. Error=%lu\n",GetLastError());
        TerminateProcess(child.hProcess,2); CloseHandle(child.hThread); CloseHandle(child.hProcess); return 1;
    }
    printf("DISPLAY_PATCH pid=%lu output=%ldx%ld logical=%dx%d ui_scale=%d vertical_fov=preserved\n",
           child.dwProcessId,physical_width,physical_height,width,height,ui_scale);
    fflush(stdout);
    WaitForInputIdle(child.hProcess,10000);
    uint32_t renderer=0, viewport=0;
    int dimensions[2]={0}, bounds[2]={0};
    read_memory(child.hProcess,0x00677e54,&renderer,4);
    read_memory(child.hProcess,0x005f56ac,&viewport,4);
    if (renderer) read_memory(child.hProcess,renderer+0xdc,dimensions,8);
    if (viewport) read_memory(child.hProcess,viewport,bounds,8);
    printf("DISPLAY_STATE renderer=%dx%d viewport=%dx%d\n",dimensions[0],dimensions[1],bounds[0],bounds[1]);
    CloseHandle(child.hThread); CloseHandle(child.hProcess);
    return 0;
}

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

_Static_assert(sizeof(void*) == 4, "Build this retail launcher for 32-bit x86.");

static const uint32_t nav_callbacks[]={0x004934f0,0x0043dda0,0x00474d20,
    0x00483850,0x0045aa20,0x004a0220,0x0041e190};

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

static int configure_resolution(const wchar_t *folder, int width, int height) {
    /* DDrawCompat accepts only advertised modes, including emulated modes.
       Preserve graphics presets and add this display's computed canvas. */
    wchar_t path[MAX_PATH], backup[MAX_PATH], temporary[MAX_PATH];
    swprintf(path,MAX_PATH,L"%ls\\DDrawCompat-wulfram2.ini",folder);
    swprintf(backup,MAX_PATH,L"%ls\\DDrawCompat-wulfram2.ini.before-display",folder);
    swprintf(temporary,MAX_PATH,L"%ls\\DDrawCompat-wulfram2.ini.%lu.tmp",folder,GetCurrentProcessId());
    FILE *input=_wfopen(path,L"rb");
    if (!input) return 0;
    char text[65536], output[66000], setting[160];
    size_t count=fread(text,1,sizeof(text)-1,input);
    int ok=!ferror(input) && feof(input); fclose(input);
    if (!ok || memchr(text,0,count)) return 0;
    text[count]=0;
    snprintf(setting,sizeof(setting),"SupportedResolutions = native, 640x480, 800x600, 1024x768, %dx%d\r\n",width,height);
    size_t used=0; int found=0;
    for (char *line=text; *line;) {
        char *end=strchr(line,'\n');
        size_t length=end ? (size_t)(end-line+1) : strlen(line);
        char *key=line; while (*key==' ' || *key=='\t') ++key;
        int match=!_strnicmp(key,"SupportedResolutions",20);
        char *equals=key+(match ? 20 : 0);
        while (*equals==' ' || *equals=='\t') ++equals;
        if (match && *equals=='=') {
            if (!found) { memcpy(output+used,setting,strlen(setting)); used+=strlen(setting); }
            found=1;
        } else { memcpy(output+used,line,length); used+=length; }
        line+=length;
    }
    if (!found) { output[used++]='\r'; output[used++]='\n'; memcpy(output+used,setting,strlen(setting)); used+=strlen(setting); }
    if (used==count && !memcmp(text,output,count)) return 1;
    if (!CopyFileW(path,backup,TRUE) && GetLastError()!=ERROR_FILE_EXISTS) return 0;
    FILE *file=_wfopen(temporary,L"wb");
    if (!file) return 0;
    ok=fwrite(output,1,used,file)==used;
    ok=fclose(file)==0 && ok;
    if (ok) ok=MoveFileExW(temporary,path,MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH);
    if (!ok) DeleteFileW(temporary);
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

/* ESI: tightly packed RGB24, EDI: same buffer, ECX: pixel count. Conversion
   runs forward so its two-byte output never overwrites unread RGB pixels. */
static void emit_rgb565(unsigned char *code, size_t *n) {
    code[(*n)++]=0x85; code[(*n)++]=0xc9;
    code[(*n)++]=0x74; size_t empty=(*n)++;
    size_t loop=*n;
    const unsigned char body[]={
        0x0f,0xb6,0x06,0xc1,0xe8,0x03,0xc1,0xe0,0x0b,
        0x0f,0xb6,0x56,0x01,0xc1,0xea,0x02,0xc1,0xe2,0x05,0x09,0xd0,
        0x0f,0xb6,0x56,0x02,0xc1,0xea,0x03,0x09,0xd0,
        0x66,0x89,0x07,0x83,0xc6,0x03,0x83,0xc7,0x02,0x49,0x75
    };
    memcpy(code+*n,body,sizeof(body)); *n+=sizeof(body);
    code[*n]=(unsigned char)(loop-*n-1); ++*n;
    code[empty]=(unsigned char)(*n-empty-1);
}

static int screenshot_self_test(void) {
    unsigned char code[128]={0x60,0x8b,0x74,0x24,0x24,0x89,0xf7,0x8b,0x4c,0x24,0x28};
    size_t n=11; emit_rgb565(code,&n); code[n++]=0x61; code[n++]=0xc3;
    void *memory=VirtualAlloc(NULL,4096,MEM_RESERVE|MEM_COMMIT,PAGE_READWRITE);
    DWORD previous;
    if (!memory) return 1;
    memcpy(memory,code,n);
    if (!VirtualProtect(memory,4096,PAGE_EXECUTE_READ,&previous)
        || !FlushInstructionCache(GetCurrentProcess(),memory,n)) { VirtualFree(memory,0,MEM_RELEASE); return 1; }
    unsigned char rgb[]={255,0,0,0,255,0,0,0,255,255,255,255,0,0,0,123,45,67};
    const uint16_t expected[]={0xf800,0x07e0,0x001f,0xffff,0x0000,0x7968};
    void (__cdecl *convert)(void*,unsigned int)=(void (__cdecl *)(void*,unsigned int))memory;
    convert(rgb,0); convert(rgb,6);
    int ok=!memcmp(rgb,expected,sizeof(expected));
    VirtualFree(memory,0,MEM_RELEASE);
    puts(ok ? "SCREENSHOT_CONVERSION=PASS" : "SCREENSHOT_CONVERSION=FAIL");
    return ok ? 0 : 1;
}

static int hook(HANDLE process, uintptr_t address, const unsigned char *original,
                size_t overwritten, const unsigned char *code, size_t size, uintptr_t resume) {
    if (size>4091 || overwritten<5 || overwritten>64) return 0;
    unsigned char payload[4096];
    memcpy(payload,code,size);
    uintptr_t remote = (uintptr_t)VirtualAllocEx(process,NULL,4096,MEM_RESERVE|MEM_COMMIT,PAGE_READWRITE);
    if (!remote) return 0;
    if (resume) {
        payload[size++]=0xe9;
        uint32_t displacement=(uint32_t)(resume-(remote+size+4));
        put32(payload,&size,displacement);
    }
    SIZE_T written = 0;
    DWORD ignored;
    if (!WriteProcessMemory(process,(LPVOID)remote,payload,size,&written) || written!=size
        || !VirtualProtectEx(process,(LPVOID)remote,4096,PAGE_EXECUTE_READ,&ignored)
        || !FlushInstructionCache(process,(LPCVOID)remote,size)) return 0;
    unsigned char branch[64]; memset(branch,0x90,sizeof(branch));
    branch[0]=0xe9;
    uint32_t offset=(uint32_t)(remote-address-5);
    memcpy(branch+1,&offset,4);
    return patch(process,address,original,branch,overwritten);
}

static int hook_self_test(void) {
    unsigned char *target=VirtualAlloc(NULL,4096,MEM_RESERVE|MEM_COMMIT,PAGE_READWRITE);
    if (!target) return 1;
    const unsigned char original[]={0x90,0x90,0x90,0x90,0x90};
    unsigned char source[]={0x90,0xaa,0xbb,0xcc,0xdd,0xee};
    const unsigned char expected[]={0x90,0xaa,0xbb,0xcc,0xdd,0xee};
    memcpy(target,original,5); target[5]=0xc3;
    DWORD protection;
    int ok=VirtualProtect(target,4096,PAGE_EXECUTE_READ,&protection)
        && hook(GetCurrentProcess(),(uintptr_t)target,original,5,source,1,(uintptr_t)(target+5));
    if (ok) {
        void (__cdecl *run)(void)=(void (__cdecl *)(void))target;
        run();
        ok=!memcmp(source,expected,sizeof(source));
        int32_t displacement; memcpy(&displacement,target+1,4);
        VirtualFree(target+5+displacement,0,MEM_RELEASE);
    }
    VirtualFree(target,0,MEM_RELEASE);
    puts(ok ? "PATCH_BUFFER=PASS" : "PATCH_BUFFER=FAIL");
    return ok ? 0 : 1;
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

static int fix_screenshot(HANDLE process) {
    /* D3D returns RGB24, but Img_SaveBmp only accepts indexed 8-bit or RGB565.
       Convert the game's own readback buffer, then use its existing BMP writer. */
    const unsigned char original[]={0x8b,0x4d,0xe8,0xc1,0xe1,0x03,0x8b,0x55,0x08};
    unsigned char code[128]={0x9c,0x60,0x8b,0x75,0xec,0x89,0xf7,0x8b,0x4d,0xfc,0x0f,0xaf,0x4d,0xf8};
    size_t n=14;
    emit_rgb565(code,&n);
    const unsigned char finish[]={0xc7,0x45,0xe8,0x02,0x00,0x00,0x00,0x61,0x9d};
    memcpy(code+n,finish,sizeof(finish)); n+=sizeof(finish);
    memcpy(code+n,original,sizeof(original)); n+=sizeof(original);
    return hook(process,0x004af629,original,sizeof(original),code,n,0x004af632);
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

static int fix_cockpit(HANDLE process, int width, int height) {
    /* Translate only the non-interactive cockpit artwork. The menu canvas,
       map selectors and mouse coordinates stay in the same screen space. */
    int x=(width-640)/2, y=height-480;
    unsigned char code[128]; size_t n=0;
    static const unsigned char original[]={0xe8,0x54,0x29,0xfe,0xff};
    emit_offset(code,&n,x,y,1);
    code[n++]=0xb8; put32(code,&n,0x00424620); code[n++]=0xff; code[n++]=0xd0;
    emit_offset(code,&n,-x,-y,1);
    if (!hook(process,0x00441cc7,original,sizeof(original),code,n,0x00441ccc)) return 0;
    /* The health/fuel meters belong to the top edge, unlike the cockpit. */
    static const unsigned char meter_call[]={0xe8,0xce,0xc5,0x02,0x00};
    n=0;
    emit_offset(code,&n,0,-y,1);
    code[n++]=0xb8; put32(code,&n,0x00450c40); code[n++]=0xff; code[n++]=0xd0;
    emit_offset(code,&n,0,y,1);
    if (!hook(process,0x0042466d,meter_call,sizeof(meter_call),code,n,0x00424672)) return 0;
    /* Team counts share the top status row with the meters. */
    static const unsigned char team_call[]={0xe8,0xdf,0xfb,0xff,0xff};
    n=0;
    emit_offset(code,&n,0,-y,1);
    code[n++]=0xb8; put32(code,&n,0x00424260); code[n++]=0xff; code[n++]=0xd0;
    emit_offset(code,&n,0,y,1);
    return hook(process,0x0042467c,team_call,sizeof(team_call),code,n,0x00424681);
}

static void emit_canvas(unsigned char *code, size_t *n, int width, int height, int x, int y) {
    const unsigned char offsets[]={0,4,0x10,0x14,0x1c,0x20,0x24,0x28};
    const int values[]={width,height,x,y,0,width-1,0,height-1};
    for (size_t i=0;i<sizeof(offsets);++i) {
        code[(*n)++]=0xc7; code[(*n)++]=0x40; code[(*n)++]=offsets[i];
        put32(code,n,(uint32_t)values[i]);
    }
}

static void resolve_branch(unsigned char *code, size_t displacement, size_t destination) {
    uint32_t relative=(uint32_t)(destination-displacement-4);
    memcpy(code+displacement,&relative,4);
}

static void emit_store(unsigned char *code, size_t *n, uintptr_t address, uint32_t value) {
    code[(*n)++]=0xc7; code[(*n)++]=0x05; put32(code,n,(uint32_t)address); put32(code,n,value);
}

static int install_lab_menu_input(HANDLE process, int width, int height, uintptr_t *mailbox) {
    /* Test-only bridge: dispatch menu mouse events on the game's UI thread.
       No OS input, arbitrary function calls, or login-dialog automation. */
    uintptr_t box=(uintptr_t)VirtualAllocEx(process,NULL,4096,MEM_RESERVE|MEM_COMMIT,PAGE_READWRITE);
    uint32_t magic=0x574c4142; SIZE_T written;
    if (!box || !WriteProcessMemory(process,(LPVOID)box,&magic,4,&written) || written!=4) return 0;
    unsigned char code[768]={0x9c,0x60,0xa1}; size_t n=3;
    put32(code,&n,(uint32_t)(box+4));
    code[n++]=0x3b; code[n++]=0x05; put32(code,&n,(uint32_t)(box+8));
    code[n++]=0x0f; code[n++]=0x84; size_t idle=n; put32(code,&n,0);
    code[n++]=0xa1; put32(code,&n,0x00677f70);
    code[n++]=0x85; code[n++]=0xc0;
    code[n++]=0x0f; code[n++]=0x84; size_t no_view=n; put32(code,&n,0);
    code[n++]=0x83; code[n++]=0x3d; put32(code,&n,(uint32_t)(box+24)); code[n++]=1;
    code[n++]=0x0f; code[n++]=0x84; size_t screenshot=n; put32(code,&n,0);
    size_t allowed[sizeof(nav_callbacks)/sizeof(*nav_callbacks)];
    for (size_t i=0;i<sizeof(allowed)/sizeof(*allowed);++i) {
        code[n++]=0x81; code[n++]=0x78; code[n++]=0x0c; put32(code,&n,nav_callbacks[i]);
        code[n++]=0x0f; code[n++]=0x84; allowed[i]=n; put32(code,&n,0);
    }
    code[n++]=0xe9; size_t not_menu=n; put32(code,&n,0);
    for (size_t i=0;i<sizeof(allowed)/sizeof(*allowed);++i) resolve_branch(code,allowed[i],n);
    size_t invalid[2];
    const int limits[]={width,height};
    for (int i=0;i<2;++i) {
        code[n++]=0xa1; put32(code,&n,(uint32_t)(box+12+4*i));
        code[n++]=0x3d; put32(code,&n,(uint32_t)limits[i]);
        code[n++]=0x0f; code[n++]=0x83; invalid[i]=n; put32(code,&n,0);
        code[n++]=0xa3; put32(code,&n,(uint32_t)(box+40+4*i));
    }
    /* Feed valid logical positions through the real WM_MOUSEMOVE clamp before
       dispatching menu events. Patched bounds keep this inside the window. */
    code[n++]=0xa1; put32(code,&n,(uint32_t)(box+16));
    code[n++]=0xc1; code[n++]=0xe0; code[n++]=16;
    code[n++]=0x0b; code[n++]=0x05; put32(code,&n,(uint32_t)(box+12));
    code[n++]=0x50; code[n++]=0xb8; put32(code,&n,0x004b89c0);
    code[n++]=0xff; code[n++]=0xd0; code[n++]=0x83; code[n++]=0xc4; code[n++]=4;
    for (int i=0;i<2;++i) {
        code[n++]=0xa1; put32(code,&n,i ? 0x00677104 : 0x00677d18);
        code[n++]=0xa3; put32(code,&n,(uint32_t)(box+40+4*i));
    }
    emit_store(code,&n,box+48,5); /* retail left mouse button */
    const uint32_t events[]={3,1,2}; /* move, press, release */
    for (size_t i=0;i<3;++i) {
        emit_store(code,&n,box+32,events[i]);
        code[n++]=0xbf; put32(code,&n,(uint32_t)(box+32)); /* EDI: event */
        code[n++]=0xb8; put32(code,&n,0x004a1960); code[n++]=0xff; code[n++]=0xd0;
    }
    emit_store(code,&n,box+20,1);
    code[n++]=0xe9; size_t accepted=n; put32(code,&n,0);
    resolve_branch(code,screenshot,n);
    code[n++]=0xb8; put32(code,&n,0x0041c040); code[n++]=0xff; code[n++]=0xd0;
    code[n++]=0x85; code[n++]=0xc0;
    code[n++]=0x0f; code[n++]=0x84; size_t capture_failed=n; put32(code,&n,0);
    emit_store(code,&n,box+20,1);
    code[n++]=0xe9; size_t captured=n; put32(code,&n,0);
    resolve_branch(code,no_view,n); resolve_branch(code,not_menu,n);
    resolve_branch(code,capture_failed,n);
    for (size_t i=0;i<2;++i) resolve_branch(code,invalid[i],n);
    emit_store(code,&n,box+20,2);
    resolve_branch(code,accepted,n);
    resolve_branch(code,captured,n);
    code[n++]=0xa1; put32(code,&n,(uint32_t)(box+4));
    code[n++]=0xa3; put32(code,&n,(uint32_t)(box+8));
    resolve_branch(code,idle,n);
    code[n++]=0x61; code[n++]=0x9d;
    code[n++]=0xb8; put32(code,&n,0x00428170); code[n++]=0xff; code[n++]=0xd0;
    const unsigned char original[]={0xe8,0x58,0xff,0xff,0xff};
    if (!hook(process,0x00428213,original,sizeof(original),code,n,0x00428218)) return 0;
    *mailbox=box;
    return 1;
}

static int fix_menu_canvas(HANDLE process, int width, int height) {
    /* The stock widget hit-test subtracts its viewer's persistent origin.
       Center the original menu canvas there, without translating input again.
       Gameplay retains the full root canvas and the existing cockpit anchors. */
    const unsigned char original[]={0x83,0x3d,0x70,0x7f,0x67,0x00,0x00};
    unsigned char code[768]={0x9c,0x60,0xa1,0xac,0x56,0x5f,0x00,0x85,0xc0,0x0f,0x84};
    size_t n=11, no_root=n; put32(code,&n,0);
    const unsigned char current[]={0x8b,0x0d,0x70,0x7f,0x67,0x00,0x85,0xc9,0x0f,0x84};
    memcpy(code+n,current,sizeof(current)); n+=sizeof(current);
    size_t no_screen=n; put32(code,&n,0);
    const size_t nav_count=sizeof(nav_callbacks)/sizeof(*nav_callbacks);
    size_t menu_branches[9];
    for (size_t i=0;i<nav_count+2;++i) {
        uint32_t callback=i<nav_count ? nav_callbacks[i] : i==nav_count ? 0x004622e0 : 0x00484a90;
        code[n++]=0x81; code[n++]=0x79; code[n++]=0x0c; put32(code,&n,callback);
        code[n++]=0x0f; code[n++]=0x84; menu_branches[i]=n; put32(code,&n,0);
    }
    resolve_branch(code,no_screen,n);
    emit_canvas(code,&n,width,height,0,0);
    code[n++]=0xe9; size_t after_wide=n; put32(code,&n,0);
    for (size_t i=0;i<nav_count+2;++i) resolve_branch(code,menu_branches[i],n);
    emit_canvas(code,&n,640,480,(width-640)/2,(height-480)/2);
    resolve_branch(code,after_wide,n);
    const unsigned char linear[]={0x8b,0x50,0x0c,0x0f,0xaf,0x50,0x14,0x03,0x50,0x10,0x89,0x50,0x18};
    memcpy(code+n,linear,sizeof(linear)); n+=sizeof(linear);
    resolve_branch(code,no_root,n);
    code[n++]=0x61; code[n++]=0x9d;
    memcpy(code+n,original,sizeof(original)); n+=sizeof(original);
    if (!hook(process,0x004281d0,original,sizeof(original),code,n,0x004281d7)) return 0;
    /* The entry/team console owns a separate viewport, selected once on entry. */
    const unsigned char console_origin[]={0x83,0xc1,0xff,0x5f,0x89,0x70,0x1c};
    n=0; emit_offset(code,&n,(width-640)/2,(height-480)/2,0);
    memcpy(code+n,console_origin,sizeof(console_origin)); n+=sizeof(console_origin);
    if (!hook(process,0x0045ea6d,console_origin,sizeof(console_origin),code,n,0x0045ea74)) return 0;
    n=0; emit_offset(code,&n,(width-640)/2,(height-480)/2,0);
    memcpy(code+n,console_origin,sizeof(console_origin)); n+=sizeof(console_origin);
    if (!hook(process,0x0045e9ad,console_origin,sizeof(console_origin),code,n,0x0045e9b4)) return 0;
    const unsigned char info_console[]={0x89,0x48,0x1c,0xc7,0x40,0x20,0x3d,0x02,0x00,0x00};
    n=0; emit_offset(code,&n,(width-640)/2,(height-480)/2,0);
    memcpy(code+n,info_console,sizeof(info_console)); n+=sizeof(info_console);
    if (!hook(process,0x0045ea03,info_console,sizeof(info_console),code,n,0x0045ea0d)) return 0;
    /* Entry map and vehicle preview allocate their own panes from local menu
       rectangles. Their pixels need the same persistent origin as the frame. */
    const unsigned char map_origin[]={0xc7,0x40,0x1c,0x00,0x00,0x00,0x00};
    n=0; emit_offset(code,&n,(width-640)/2,(height-480)/2,0);
    memcpy(code+n,map_origin,sizeof(map_origin)); n+=sizeof(map_origin);
    if (!hook(process,0x0043c5ec,map_origin,sizeof(map_origin),code,n,0x0043c5f3)) return 0;
    const unsigned char preview_origin[]={0x89,0x78,0x1c,0x89,0x50,0x20};
    n=0; emit_offset(code,&n,(width-640)/2,(height-480)/2,0);
    memcpy(code+n,preview_origin,sizeof(preview_origin)); n+=sizeof(preview_origin);
    if (!hook(process,0x0043cf51,preview_origin,sizeof(preview_origin),code,n,0x0043cf57)) return 0;
    /* Both Units Info model panes use the same viewport constructor. */
    const unsigned char briefing_origin[]={0x89,0x7e,0x1c,0x89,0x4e,0x20};
    n=0; code[n++]=0x50; code[n++]=0x89; code[n++]=0xf0;
    emit_offset(code,&n,(width-640)/2,(height-480)/2,0);
    code[n++]=0x58;
    memcpy(code+n,briefing_origin,sizeof(briefing_origin)); n+=sizeof(briefing_origin);
    if (!hook(process,0x0049f005,briefing_origin,sizeof(briefing_origin),code,n,0x0049f00b)) return 0;
    /* This custom map picker bypasses Widget_HitTestPoint's origin transform.
       Translate only its cursor arguments; all ordinary widget input is intact. */
    const unsigned char map_cursor[]={0x8b,0x48,0x0c,0x8b,0x50,0x08};
    memcpy(code,map_cursor,sizeof(map_cursor)); n=sizeof(map_cursor);
    code[n++]=0x81; code[n++]=0xe9; put32(code,&n,(uint32_t)((height-480)/2));
    code[n++]=0x81; code[n++]=0xea; put32(code,&n,(uint32_t)((width-640)/2));
    if (!hook(process,0x0043bec3,map_cursor,sizeof(map_cursor),code,n,0x0043bec9)) return 0;
    /* Polygon-shaped tabs/buttons run a second local hit test after the base
       widget gate. Normalize its raw screen arguments by the same viewer. */
    const unsigned char button_entry[]={0x51,0xd9,0x44,0x24,0x08};
    const unsigned char local_point[]={
        0x52,0x8b,0x50,0x18,
        0xd9,0x44,0x24,0x08,0xda,0x62,0x10,0xd9,0x5c,0x24,0x08,
        0xd9,0x44,0x24,0x0c,0xda,0x62,0x14,0xd9,0x5c,0x24,0x0c,0x5a
    };
    memcpy(code,local_point,sizeof(local_point)); n=sizeof(local_point);
    memcpy(code+n,button_entry,sizeof(button_entry)); n+=sizeof(button_entry);
    return hook(process,0x00412320,button_entry,sizeof(button_entry),code,n,0x00412325);
}

static void emit_clear_rect(unsigned char *code, size_t *n, int left, int top, int right, int bottom) {
    const int args[]={0,bottom,right,top,left};
    for (size_t i=0;i<5;++i) { code[(*n)++]=0x68; put32(code,n,(uint32_t)args[i]); }
    code[(*n)++]=0xff; code[(*n)++]=0x35; put32(code,n,0x005f56ac);
    code[(*n)++]=0xa1; put32(code,n,0x00677e54);
    const unsigned char call[]={0xff,0x50,0x6c,0x83,0xc4,0x18};
    memcpy(code+*n,call,sizeof(call)); *n+=sizeof(call);
}

static int fix_menu_margins(HANDLE process, int width, int height) {
    /* Clear startup-console leftovers outside the menu after drawing it. */
    int x=(width-640)/2, y=(height-480)/2;
    unsigned char code[512]={0x9c,0x60,0xa1,0xac,0x56,0x5f,0x00,0x85,0xc0,0x0f,0x84};
    size_t n=11, absent=n; put32(code,&n,0);
    code[n++]=0x81; code[n++]=0x38; put32(code,&n,640);
    code[n++]=0x0f; code[n++]=0x85; size_t game=n; put32(code,&n,0);
    code[n++]=0x81; code[n++]=0x78; code[n++]=4; put32(code,&n,480);
    code[n++]=0x0f; code[n++]=0x85; size_t game_height=n; put32(code,&n,0);
    emit_canvas(code,&n,width,height,0,0);
    code[n++]=0xc7; code[n++]=0x40; code[n++]=0x18; put32(code,&n,0);
    if (x>0) { emit_clear_rect(code,&n,0,0,x-1,height-1); emit_clear_rect(code,&n,x+640,0,width-1,height-1); }
    if (y>0) { emit_clear_rect(code,&n,x,0,x+639,y-1); emit_clear_rect(code,&n,x,y+480,x+639,height-1); }
    code[n++]=0xa1; put32(code,&n,0x005f56ac);
    emit_canvas(code,&n,640,480,x,y);
    emit_offset(code,&n,0,0,0);
    resolve_branch(code,absent,n); resolve_branch(code,game,n); resolve_branch(code,game_height,n);
    code[n++]=0x61; code[n++]=0x9d;
    code[n++]=0xb8; put32(code,&n,0x004a7b00); code[n++]=0xff; code[n++]=0xd0;
    const unsigned char original[]={0xe8,0xfc,0xf8,0x07,0x00};
    return hook(process,0x004281ff,original,sizeof(original),code,n,0x00428204);
}

static int fix_full_view_read(HANDLE process, int width, int height,
        uint32_t address, const unsigned char original[6], unsigned char target_register) {
    /* Readbacks and the software cursor use screen coordinates. Give only
       those operations a full-framebuffer descriptor; retain widget origins. */
    uintptr_t full=(uintptr_t)VirtualAllocEx(process,NULL,4096,MEM_RESERVE|MEM_COMMIT,PAGE_READWRITE);
    if (!full) return 0;
    unsigned char code[128]={0x9c,0x60,0xfc,0x8b,0x35,0xac,0x56,0x5f,0x00,0xbf};
    size_t n=10; put32(code,&n,(uint32_t)full);
    code[n++]=0xb9; put32(code,&n,15); code[n++]=0xf3; code[n++]=0xa5;
    code[n++]=0xb8; put32(code,&n,(uint32_t)full);
    emit_canvas(code,&n,width,height,0,0);
    code[n++]=0xc7; code[n++]=0x40; code[n++]=0x18; put32(code,&n,0);
    code[n++]=0x61; code[n++]=0x9d;
    code[n++]=target_register; put32(code,&n,(uint32_t)full);
    return hook(process,address,original,6,code,n,address+6);
}

static int fix_mouse_screen_space(HANDLE process, int width, int height) {
    /* Menu bounds must not clamp WM_MOUSEMOVE to 640x480. */
    const unsigned char x_compare[]={0x8b,0x55,0xf8,0x3b,0x11};
    unsigned char code[32]={0x8b,0x55,0xf8,0x81,0xfa}; size_t n=5;
    put32(code,&n,(uint32_t)width);
    if (!hook(process,0x004b89f8,x_compare,5,code,n,0x004b89fd)) return 0;
    const unsigned char x_limit[]={0x8b,0x08,0x83,0xe9,0x01};
    n=0; code[n++]=0xb9; put32(code,&n,(uint32_t)(width-1));
    if (!hook(process,0x004b8a04,x_limit,5,code,n,0x004b8a09)) return 0;
    const unsigned char y_compare[]={0x8b,0x45,0xfc,0x3b,0x42,0x04};
    memcpy(code,y_compare,3); n=3; code[n++]=0x3d; put32(code,&n,(uint32_t)height);
    if (!hook(process,0x004b8a16,y_compare,6,code,n,0x004b8a1c)) return 0;
    const unsigned char y_limit[]={0x8b,0x51,0x04,0x83,0xea,0x01};
    n=0; code[n++]=0xba; put32(code,&n,(uint32_t)(height-1));
    if (!hook(process,0x004b8a24,y_limit,6,code,n,0x004b8a2a)) return 0;
    /* Cursor input is absolute; its blit receives coordinates local to root. */
    const unsigned char original[]={0x8b,0x55,0x10,0x52,0x8b,0x45,0x0c,0x50};
    unsigned char local[]={0x8b,0x0d,0xac,0x56,0x5f,0x00,
        0x8b,0x55,0x10,0x2b,0x51,0x14,0x52,
        0x8b,0x45,0x0c,0x2b,0x41,0x10,0x50};
    return hook(process,0x004b3b69,original,sizeof(original),local,sizeof(local),0x004b3b71)
        && hook(process,0x004a8f0d,original,sizeof(original),local,sizeof(local),0x004a8f15);
}

static int patch_display(HANDLE process, int width, int height) {
    const unsigned char overview_read[]={0x8b,0x0d,0xac,0x56,0x5f,0x00};
    const int old_width=640, old_height=480;
    const int old_scene[2]={640,360}, scene[2]={width,height-120};
    const int old_full[2]={640,480}, full[2]={width,height};
    const int old_radar[2]={3,346}, radar[2]={3+(width-640)/2,height-134};
    const int old_secondary[2]={533,366}, secondary[2]={533+(width-640)/2,height-114};
    const int old_console_min[2]={142,358}, console_min[2]={142+(width-640)/2,height-122};
    const int old_console_max[2]={510,458}, console_max[2]={510+(width-640)/2,height-22};
    return patch(process,0x004a8137,&old_width,&width,4)
        && patch(process,0x004a813e,&old_height,&height,4)
        && patch(process,0x00577a20,old_scene,scene,8)
        && patch(process,0x00577ac0,old_full,full,8)
        && patch(process,0x00577ac8,old_full,full,8)
        && patch(process,0x00577a40,old_radar,radar,8)
        && patch(process,0x00577a80,old_secondary,secondary,8)
        && patch(process,0x00577ae0,old_console_min,console_min,8)
        && patch(process,0x00577b00,old_console_max,console_max,8)
        && fix_projection(process,width,height)
        && fix_cockpit(process,width,height)
        && fix_menu_canvas(process,width,height)
        && fix_menu_margins(process,width,height)
        && fix_full_view_read(process,width,height,0x0047b280,overview_read,0xb9)
        && fix_mouse_screen_space(process,width,height)
        && fix_screenshot(process);
}

static int valid_lab_desktop(const wchar_t *name) {
    return wcslen(name)==43 && !wcsncmp(name,L"WulframLab-",11)
        && wcsspn(name+11,L"0123456789abcdef")==32;
}

static int desktop_self_test(void) {
    const wchar_t *invalid[]={L"Default",L"WinSta0\\Default",L"WulframLab-",
        L"WulframLab-0000000000000000000000000000000g",
        L"WulframLab-000000000000000000000000000000000"};
    int ok=valid_lab_desktop(L"WulframLab-0123456789abcdef0123456789abcdef");
    for (size_t i=0;i<sizeof(invalid)/sizeof(*invalid);++i) ok=ok && !valid_lab_desktop(invalid[i]);
    puts(ok ? "LAB_DESKTOP_BOUNDARY=PASS" : "LAB_DESKTOP_BOUNDARY=FAIL");
    return ok ? 0 : 1;
}

int wmain(int argc, wchar_t **argv) {
    if (argc==2 && !wcscmp(argv[1],L"--self-test")) return screenshot_self_test() || hook_self_test() || desktop_self_test();
    int lab=((argc==6 || argc==7) && !wcscmp(argv[5],L"--lab"))
        || (argc==6 && !wcscmp(argv[5],L"--lab-view"));
    if (argc != 2 && argc != 3 && argc != 4 && argc != 5 && !lab) {
        fwprintf(stderr,L"Usage: wulfram-display.exe CLIENT_DIRECTORY [SERVER] or [WIDTH HEIGHT [SERVER]]\n");
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
    /* Keep UI proportions consistent across pixel densities. DDrawCompat's
       display(1) profile renders 3D at the native display resolution. */
    int height=physical_height<720 ? 480 : 540;
    int width=(int)((physical_width*height+physical_height/2)/physical_height);
    if (width<640) { width=640; height=(int)((physical_height*640+physical_width/2)/physical_width); }
    /* Retail RGB readback assumes DWORD-aligned rows; odd canvas widths can
       corrupt adjacent allocations when the 3D framebuffer is copied. */
    width=(width+3)&~3;
    double ui_scale=(double)physical_height/height;
    const wchar_t *server=argc>=5 ? argv[4] : argc==3 ? argv[2] : L"wulfram.canadaverse.org";
    if (!*server || wcslen(server)>253 || wcsspn(server,L"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-")!=wcslen(server)) return 2;
    long port=2627;
    if (lab) {
        wchar_t port_text[8], *end;
        DWORD count=GetEnvironmentVariableW(L"WULFRAM_LAB_PORT",port_text,8);
        if (count>=8) return 2;
        if (count) { port=wcstol(port_text,&end,10); if (*end || port<1 || port>65535) return 2; }
    }
    wchar_t folder[MAX_PATH], executable[MAX_PATH], command[1024];
    DWORD length=GetFullPathNameW(argv[1],MAX_PATH,folder,NULL);
    if (!length || length>MAX_PATH-65) return 2;
    swprintf(executable,MAX_PATH,L"%ls\\wulfram2.exe",folder);
    if (!verify_exe(executable)) { fputs("Unsupported Wulfram executable. No process started.\n",stderr); return 2; }
    if (!configure_resolution(folder,width,height)) {
        fputs("Could not prepare this display. Extract the complete game into a writable Games folder.\n",stderr); return 2;
    }
    swprintf(command,1024,L"\"%ls\" -root -server %ls -port %ld",executable,server,port);
    if (lab && !wcscmp(argv[5],L"--lab")) {
        wchar_t password[128];
        DWORD count=GetEnvironmentVariableW(L"WULFRAM_LAB_PASSWORD",password,128);
        if (!count || count>=128 || wcspbrk(password,L" \t\r\n\"\\")) return 2;
        if (argc==7 && wcscmp(argv[6],L"red") && wcscmp(argv[6],L"blue")) return 2;
        swprintf(command,1024,L"\"%ls\" -root -server %ls -port %ld -login ClientLab %ls%ls%ls",
                 executable,server,port,password,argc==7 ? L" -side " : L"",argc==7 ? argv[6] : L"");
        SecureZeroMemory(password,sizeof(password));
    }
    STARTUPINFOW startup = {0}; startup.cb=sizeof(startup);
    wchar_t desktop_name[80]={0};
    HDESK desktop=NULL;
    if (lab) {
        DWORD count=GetEnvironmentVariableW(L"WULFRAM_LAB_DESKTOP",desktop_name,80);
        if (count) {
            if (count>=80 || !valid_lab_desktop(desktop_name)) {
                fputs("Invalid private lab desktop name.\n",stderr); return 2;
            }
            desktop=CreateDesktopW(desktop_name,NULL,NULL,0,
                DESKTOP_CREATEWINDOW|DESKTOP_READOBJECTS|DESKTOP_WRITEOBJECTS|DESKTOP_ENUMERATE,NULL);
            if (!desktop) { fprintf(stderr,"Private desktop creation failed: %lu\n",GetLastError()); return 1; }
            startup.lpDesktop=desktop_name;
        }
    }
    PROCESS_INFORMATION child={0};
    if (!CreateProcessW(executable,command,NULL,NULL,FALSE,CREATE_SUSPENDED,NULL,folder,&startup,&child)) {
        if (desktop) CloseDesktop(desktop);
        fprintf(stderr,"Launch failed: %lu\n",GetLastError()); return 1;
    }
    uintptr_t mailbox=0;
    if (!patch_display(child.hProcess,width,height)
        || (lab && !install_lab_menu_input(child.hProcess,width,height,&mailbox))
        || ResumeThread(child.hThread)==(DWORD)-1) {
        fprintf(stderr,"Display signatures/write failed; stopping only the new suspended child. Error=%lu\n",GetLastError());
        TerminateProcess(child.hProcess,2); CloseHandle(child.hThread); CloseHandle(child.hProcess);
        if (desktop) CloseDesktop(desktop);
        return 1;
    }
    printf("DISPLAY_PATCH pid=%lu output=%ldx%ld logical=%dx%d ui_scale=%.3f vertical_fov=preserved\n",
           child.dwProcessId,physical_width,physical_height,width,height,ui_scale);
    if (mailbox) printf("CLIENT_LAB_MAILBOX=%lu\n",(unsigned long)mailbox);
    if (desktop) printf("CLIENT_LAB_DESKTOP=%ls\n",desktop_name);
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
    if (desktop) CloseDesktop(desktop);
    return 0;
}

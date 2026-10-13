/* Execute only verified retail coordinate routines in this test process.
   The game entry point, DLL imports, renderer and networking never run. */
#define wmain display_launcher_main
#include "wulfram-display.c"
#undef wmain

static unsigned char *image;
static size_t image_size;
static POINT warped;
static unsigned int warp_count, checks, failures;
static int canvas[15], viewer[16], observed_origin[2];

static void expect(int condition, const char *label, int width, int height) {
    ++checks;
    if (!condition) {
        ++failures;
        printf("FAIL %s logical=%dx%d\n",label,width,height);
    }
}

static BOOL WINAPI fake_client_to_screen(HWND window, POINT *point) {
    (void)window;
    point->x+=100; point->y+=200;
    return TRUE;
}

static BOOL WINAPI fake_set_cursor(int x, int y) {
    warped.x=x; warped.y=y; ++warp_count;
    return TRUE;
}

static void capture_origin(void) {
    observed_origin[0]=canvas[4]; observed_origin[1]=canvas[5];
}

static void jump_to(uintptr_t from, uintptr_t to) {
    unsigned char *code=(unsigned char*)from;
    code[0]=0xe9;
    int32_t relative=(int32_t)(to-from-5);
    memcpy(code+1,&relative,4);
}

static int load_retail_image(const wchar_t *path) {
    /* Hold a read-only, non-write-shared handle while verifying and reading. */
    HANDLE file=CreateFileW(path,GENERIC_READ,FILE_SHARE_READ,NULL,OPEN_EXISTING,0,NULL);
    LARGE_INTEGER length;
    if (file==INVALID_HANDLE_VALUE) return 0;
    if (!verify_exe(path) || !GetFileSizeEx(file,&length) || length.QuadPart>16*1024*1024) {
        CloseHandle(file); return 0;
    }
    unsigned char *data=(unsigned char*)malloc((size_t)length.QuadPart);
    DWORD read=0;
    int ok=data && ReadFile(file,data,(DWORD)length.QuadPart,&read,NULL) && read==length.QuadPart;
    CloseHandle(file);
    if (!ok) { free(data); return 0; }
    IMAGE_DOS_HEADER *dos=(IMAGE_DOS_HEADER*)data;
    IMAGE_NT_HEADERS32 *nt=(IMAGE_NT_HEADERS32*)(data+dos->e_lfanew);
    if (nt->Signature!=IMAGE_NT_SIGNATURE || nt->FileHeader.Machine!=IMAGE_FILE_MACHINE_I386
            || nt->OptionalHeader.ImageBase!=0x00400000 || nt->OptionalHeader.SizeOfImage>16*1024*1024) {
        free(data); return 0;
    }
    image_size=nt->OptionalHeader.SizeOfImage;
    image=(unsigned char*)VirtualAlloc((void*)0x00400000,image_size,MEM_RESERVE|MEM_COMMIT,PAGE_READWRITE);
    if (image!=(unsigned char*)0x00400000) { free(data); return 0; }
    memcpy(image,data,nt->OptionalHeader.SizeOfHeaders);
    IMAGE_SECTION_HEADER *section=IMAGE_FIRST_SECTION(nt);
    for (unsigned int i=0;i<nt->FileHeader.NumberOfSections;++i) {
        if ((uint64_t)section[i].VirtualAddress+section[i].SizeOfRawData>image_size
                || (uint64_t)section[i].PointerToRawData+section[i].SizeOfRawData>(uint64_t)length.QuadPart) {
            VirtualFree(image,0,MEM_RELEASE); image=NULL; free(data); return 0;
        }
        memcpy(image+section[i].VirtualAddress,data+section[i].PointerToRawData,section[i].SizeOfRawData);
    }
    free(data);
    DWORD previous;
    if (!VirtualProtect(image,image_size,PAGE_EXECUTE_READWRITE,&previous)) {
        VirtualFree(image,0,MEM_RELEASE); image=NULL; return 0;
    }
    return 1;
}

/* Bridge the retail EAX-object / callee-pops-float-arguments ABI. */
static void *make_hit_bridge(uintptr_t target) {
    unsigned char code[]={0x55,0x8b,0xec,0x53,0x56,0x57,0x8b,0x45,0x08,
        0xff,0x75,0x10,0xff,0x75,0x0c,0xba,0,0,0,0,0xff,0xd2,
        0x0f,0xb6,0xc0,0x5f,0x5e,0x5b,0x5d,0xc3};
    memcpy(code+16,&target,4);
    void *memory=VirtualAlloc(NULL,4096,MEM_COMMIT|MEM_RESERVE,PAGE_READWRITE);
    if (!memory) return NULL;
    memcpy(memory,code,sizeof(code));
    DWORD old;
    if (!VirtualProtect(memory,4096,PAGE_EXECUTE_READ,&old)
            || !FlushInstructionCache(GetCurrentProcess(),memory,sizeof(code))) {
        VirtualFree(memory,0,MEM_RELEASE); return NULL;
    }
    return memory;
}

static int bridge_self_test(void) {
    /* The test callee returns object[1] in AL and pops two float arguments. */
    unsigned char code[]={0x8b,0x40,0x04,0xc2,0x08,0x00};
    void *callee=VirtualAlloc(NULL,4096,MEM_COMMIT|MEM_RESERVE,PAGE_READWRITE);
    if (!callee) return 1;
    memcpy(callee,code,sizeof(code));
    DWORD old;
    if (!VirtualProtect(callee,4096,PAGE_EXECUTE_READ,&old)
            || !FlushInstructionCache(GetCurrentProcess(),callee,sizeof(code))) return 1;
    void *bridge=make_hit_bridge((uintptr_t)callee);
    if (!bridge) return 1;
    int (__cdecl *hit)(void*,float,float)=(int (__cdecl *)(void*,float,float))bridge;
    int object[]={0,1};
    int ok=hit(object,2.f,3.f)==1;
    object[1]=0;
    ok=ok && hit(object,2.f,3.f)==0 && (uintptr_t)GetModuleHandleW(NULL)!=0x00400000;
    VirtualFree(bridge,0,MEM_RELEASE); VirtualFree(callee,0,MEM_RELEASE);
    puts(ok ? "RETAIL_LAYOUT_ABI=PASS" : "RETAIL_LAYOUT_ABI=FAIL");
    return ok ? 0 : 1;
}

static int run_layout(const wchar_t *path, int width, int height) {
    if (!load_retail_image(path)) { fputs("Verified retail image could not be mapped.\n",stderr); return 0; }
    int ok=patch_display(GetCurrentProcess(),width,height);
    if (!ok) { VirtualFree(image,0,MEM_RELEASE); image=NULL; return 0; }
    *(uintptr_t*)0x005f56ac=(uintptr_t)canvas;
    *(uintptr_t*)0x00677f70=(uintptr_t)viewer;
    *(uintptr_t*)0x0053c2c4=(uintptr_t)fake_client_to_screen;
    *(uintptr_t*)0x0053c2e0=(uintptr_t)fake_set_cursor;
    *(uintptr_t*)0x005f55cc=1;
    /* Return immediately after the injected canvas/cockpit fragments. */
    *(unsigned char*)0x004281d7=0xc3;
    *(unsigned char*)0x00441ccc=0xc3;
    *(unsigned char*)0x00424672=0xc3;
    *(unsigned char*)0x00424681=0xc3;
    jump_to(0x00424620,(uintptr_t)capture_origin);
    jump_to(0x00450c40,(uintptr_t)capture_origin);
    jump_to(0x00424260,(uintptr_t)capture_origin);
    FlushInstructionCache(GetCurrentProcess(),image,image_size);
    memset(canvas,0,sizeof(canvas)); memset(viewer,0,sizeof(viewer));
    canvas[3]=width; canvas[13]=width; canvas[14]=height;
    void (__cdecl *set_canvas)(void)=(void (__cdecl *)(void))0x004281d0;
    const int menu_x=(width-640)/2, menu_y=(height-480)/2;
    for (size_t i=0;i<sizeof(nav_callbacks)/sizeof(*nav_callbacks)+2;++i) {
        viewer[3]=i<7 ? nav_callbacks[i] : i==7 ? 0x004622e0 : 0x00484a90;
        set_canvas();
        expect(canvas[0]==640 && canvas[1]==480 && canvas[4]==menu_x && canvas[5]==menu_y
            && canvas[6]==menu_y*width+menu_x && canvas[8]==639 && canvas[10]==479,
            "menu canvas",width,height);
    }
    viewer[3]=0; set_canvas();
    expect(canvas[0]==width && canvas[1]==height && canvas[4]==0 && canvas[5]==0
        && canvas[6]==0 && canvas[8]==width-1 && canvas[10]==height-1,"world canvas",width,height);
    ((void (__cdecl *)(void))0x00441cc7)();
    expect(observed_origin[0]==menu_x && observed_origin[1]==height-480
        && canvas[4]==0 && canvas[5]==0,"cockpit anchor and restore",width,height);
    canvas[4]=menu_x; canvas[5]=height-480;
    ((void (__cdecl *)(void))0x0042466d)();
    expect(observed_origin[1]==0 && canvas[5]==height-480,"top meters",width,height);
    ((void (__cdecl *)(void))0x0042467c)();
    expect(observed_origin[1]==0 && canvas[5]==height-480,"top team counts",width,height);
    viewer[3]=nav_callbacks[0]; set_canvas();
    void (__cdecl *move)(LPARAM)=(void (__cdecl *)(LPARAM))0x004b89c0;
    const int points[][2]={{0,0},{1,1},{width-1,height-1},{width+7,height+9},{-1,10},{10,-1},{-32768,-32768},{32767,32767}};
    for (size_t i=0;i<sizeof(points)/sizeof(*points);++i) {
        int x=points[i][0],y=points[i][1];
        int ex=x<0 ? 0 : x>=width ? width-1 : x;
        int ey=y<0 ? 0 : y>=height ? height-1 : y;
        warp_count=0;
        move((LPARAM)(((uint32_t)(uint16_t)y<<16)|(uint16_t)x));
        expect(*(int*)0x00677d18==ex && *(int*)0x00677104==ey,"signed mouse bounds",width,height);
        expect((x==ex && y==ey) ? warp_count==0
            : warp_count==1 && warped.x==ex+100 && warped.y==ey+200,"cursor correction stub",width,height);
    }
    unsigned char widget[512]={0};
    *(int*)(widget+4)=20; *(int*)(widget+8)=30;
    *(uintptr_t*)(widget+0x18)=(uintptr_t)canvas;
    *(int*)(widget+0x1b4)=4;
    const float planes[][3]={{1,0,0},{-1,0,100},{0,1,0},{0,-1,30}};
    memcpy(widget+0x34,planes,sizeof(planes));
    void *bridge=make_hit_bridge(0x00412320);
    if (!bridge) { VirtualFree(image,0,MEM_RELEASE); image=NULL; return 0; }
    int (__cdecl *hit)(void*,float,float)=(int (__cdecl *)(void*,float,float))bridge;
    expect(hit(widget,(float)(menu_x+21),(float)(menu_y+31))==1,"polygon click inside",width,height);
    expect(hit(widget,(float)(menu_x+19),(float)(menu_y+31))==0,"polygon click outside left",width,height);
    expect(hit(widget,(float)(menu_x+121),(float)(menu_y+31))==0,"polygon click outside right",width,height);
    VirtualFree(bridge,0,MEM_RELEASE);
    VirtualFree(image,0,MEM_RELEASE); image=NULL;
    return 1;
}

int wmain(int argc, wchar_t **argv) {
    if (argc==2 && !wcscmp(argv[1],L"--self-test")) return bridge_self_test();
    if (argc!=2) { fputs("Usage: wulfram-layout-check.exe VERIFIED_RETAIL_EXE\n",stderr); return 2; }
    const int sizes[][2]={{640,480},{720,540},{864,540},{960,540},{1280,540},{1296,540},{1920,540},{676,540}};
    for (size_t i=0;i<sizeof(sizes)/sizeof(*sizes);++i) {
        if (!run_layout(argv[1],sizes[i][0],sizes[i][1])) {
            fputs("Retail signatures or layout fixture failed.\n",stderr); return 1;
        }
    }
    printf("RETAIL_LAYOUT checks=%u failures=%u physical_display_qualified=false\n",checks,failures);
    return failures ? 1 : 0;
}

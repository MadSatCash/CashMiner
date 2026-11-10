#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <stdlib.h>
#include <stdio.h>

#ifdef _WIN32
#define DLL_EXPORT __declspec(dllexport)
#else
#define DLL_EXPORT __attribute__((visibility("default")))
#endif

#define CL_TARGET_OPENCL_VERSION 120
#include <CL/cl.h>

typedef struct {
    uint64_t hashes_done;
    uint32_t last_nonce;
    uint32_t found_nonce;
    uint8_t found;
    uint8_t found_hash[32];
} hashscan_result_t;

typedef struct {
    cl_platform_id platform;
    cl_device_id device;
    int initialized;
    char name[256];
} opencl_device_info_t;

static opencl_device_info_t g_devices[32];
static int g_devices_loaded = 0;
static int g_device_count = 0;

static const char *OPENCL_KERNEL_SRC =
"typedef unsigned char  u8;\n"
"typedef unsigned int   u32;\n"
"typedef unsigned long  u64;\n"
"\n"
"u32 rotr32(u32 x, uint n){ return (x >> n) | (x << (32 - n)); }\n"
"u32 Ch(u32 x, u32 y, u32 z){ return (x & y) ^ (~x & z); }\n"
"u32 Maj(u32 x, u32 y, u32 z){ return (x & y) ^ (x & z) ^ (y & z); }\n"
"u32 BSIG0(u32 x){ return rotr32(x,2) ^ rotr32(x,13) ^ rotr32(x,22); }\n"
"u32 BSIG1(u32 x){ return rotr32(x,6) ^ rotr32(x,11) ^ rotr32(x,25); }\n"
"u32 SSIG0(u32 x){ return rotr32(x,7) ^ rotr32(x,18) ^ (x >> 3); }\n"
"u32 SSIG1(u32 x){ return rotr32(x,17) ^ rotr32(x,19) ^ (x >> 10); }\n"
"\n"
"u32 load_be32_private(const u8 *p){\n"
"    return ((u32)p[0] << 24) | ((u32)p[1] << 16) | ((u32)p[2] << 8) | (u32)p[3];\n"
"}\n"
"\n"
"void store_be32_private(u8 *p, u32 v){\n"
"    p[0] = (u8)(v >> 24);\n"
"    p[1] = (u8)(v >> 16);\n"
"    p[2] = (u8)(v >> 8);\n"
"    p[3] = (u8)(v);\n"
"}\n"
"\n"
"void store_le32_private(u8 *p, u32 v){\n"
"    p[0] = (u8)(v);\n"
"    p[1] = (u8)(v >> 8);\n"
"    p[2] = (u8)(v >> 16);\n"
"    p[3] = (u8)(v >> 24);\n"
"}\n"
"\n"
"__constant u32 K[64] = {\n"
"    0x428a2f98U,0x71374491U,0xb5c0fbcfU,0xe9b5dba5U,0x3956c25bU,0x59f111f1U,0x923f82a4U,0xab1c5ed5U,\n"
"    0xd807aa98U,0x12835b01U,0x243185beU,0x550c7dc3U,0x72be5d74U,0x80deb1feU,0x9bdc06a7U,0xc19bf174U,\n"
"    0xe49b69c1U,0xefbe4786U,0x0fc19dc6U,0x240ca1ccU,0x2de92c6fU,0x4a7484aaU,0x5cb0a9dcU,0x76f988daU,\n"
"    0x983e5152U,0xa831c66dU,0xb00327c8U,0xbf597fc7U,0xc6e00bf3U,0xd5a79147U,0x06ca6351U,0x14292967U,\n"
"    0x27b70a85U,0x2e1b2138U,0x4d2c6dfcU,0x53380d13U,0x650a7354U,0x766a0abbU,0x81c2c92eU,0x92722c85U,\n"
"    0xa2bfe8a1U,0xa81a664bU,0xc24b8b70U,0xc76c51a3U,0xd192e819U,0xd6990624U,0xf40e3585U,0x106aa070U,\n"
"    0x19a4c116U,0x1e376c08U,0x2748774cU,0x34b0bcb5U,0x391c0cb3U,0x4ed8aa4aU,0x5b9cca4fU,0x682e6ff3U,\n"
"    0x748f82eeU,0x78a5636fU,0x84c87814U,0x8cc70208U,0x90befffaU,0xa4506cebU,0xbef9a3f7U,0xc67178f2U\n"
"};\n"
"\n"
"__constant u32 H0[8] = {\n"
"    0x6a09e667U,0xbb67ae85U,0x3c6ef372U,0xa54ff53aU,\n"
"    0x510e527fU,0x9b05688cU,0x1f83d9abU,0x5be0cd19U\n"
"};\n"
"\n"
"void sha256_compress_private(u32 state[8], const u8 block[64]){\n"
"    u32 W[64];\n"
"    for(int i=0;i<16;++i) W[i] = load_be32_private(block + i*4);\n"
"    for(int i=16;i<64;++i) W[i] = SSIG1(W[i-2]) + W[i-7] + SSIG0(W[i-15]) + W[i-16];\n"
"\n"
"    u32 a=state[0], b=state[1], c=state[2], d=state[3];\n"
"    u32 e=state[4], f=state[5], g=state[6], h=state[7];\n"
"\n"
"    for(int i=0;i<64;++i){\n"
"        u32 t1 = h + BSIG1(e) + Ch(e,f,g) + K[i] + W[i];\n"
"        u32 t2 = BSIG0(a) + Maj(a,b,c);\n"
"        h = g; g = f; f = e; e = d + t1;\n"
"        d = c; c = b; b = a; a = t1 + t2;\n"
"    }\n"
"\n"
"    state[0] += a; state[1] += b; state[2] += c; state[3] += d;\n"
"    state[4] += e; state[5] += f; state[6] += g; state[7] += h;\n"
"}\n"
"\n"
"void sha256_80bytes(const u8 header80[80], u8 out32[32]){\n"
"    u8 block0[64];\n"
"    u8 block1[64];\n"
"    u32 state[8];\n"
"\n"
"    for(int i=0;i<8;++i) state[i] = H0[i];\n"
"\n"
"    for(int i=0;i<64;++i) block0[i] = header80[i];\n"
"\n"
"    for(int i=0;i<64;++i) block1[i] = 0;\n"
"    for(int i=0;i<16;++i) block1[i] = header80[64+i];\n"
"    block1[16] = 0x80;\n"
"    block1[62] = 0x02;\n"
"    block1[63] = 0x80;\n"
"\n"
"    sha256_compress_private(state, block0);\n"
"    sha256_compress_private(state, block1);\n"
"\n"
"    for(int i=0;i<8;++i) store_be32_private(out32 + i*4, state[i]);\n"
"}\n"
"\n"
"void sha256_32bytes(const u8 in32[32], u8 out32[32]){\n"
"    u8 block[64];\n"
"    u32 state[8];\n"
"    for(int i=0;i<8;++i) state[i] = H0[i];\n"
"    for(int i=0;i<64;++i) block[i] = 0;\n"
"    for(int i=0;i<32;++i) block[i] = in32[i];\n"
"    block[32] = 0x80;\n"
"    block[62] = 0x01;\n"
"    block[63] = 0x00;\n"
"    sha256_compress_private(state, block);\n"
"    for(int i=0;i<8;++i) store_be32_private(out32 + i*4, state[i]);\n"
"}\n"
"\n"
"int hash_le_less_than_target(const u8 hash_le32[32], __global const u8 *target_le32){"
"    for(int i=31;i>=0;--i){"
"        u8 h = hash_le32[i];"
"        u8 t = target_le32[i];"
"        if(h < t) return 1;"
"        if(h > t) return 0;"
"    }"
"    return 1;"
"}\n"
"\n"
"__kernel void opencl_scan_kernel(\n"
"    __global const u8 *header_prefix76,\n"
"    __global const u8 *target_le32,\n"
"    const u32 start_nonce,\n"
"    const u32 step,\n"
"    const u64 max_hashes,\n"
"    __global u32 *found_flag,\n"
"    __global u32 *found_nonce,\n"
"    __global u8  *found_hash_le32,\n"
"    __global u32 *last_nonce_out,\n"
"    __global u64 *hashes_done_out\n"
"){\n"
"    u64 gid = (u64)get_global_id(0);\n"
"    if(gid >= max_hashes) return;\n"
"\n"
"    u32 nonce = start_nonce + (u32)(gid * (u64)step);\n"
"\n"
"    u8 header80[80];\n"
"    u8 hash1[32];\n"
"    u8 hash2_be[32];\n"
"    u8 hash2_le[32];\n"
"\n"
"    for(int i=0;i<76;++i) header80[i] = header_prefix76[i];\n"
"    store_le32_private(header80 + 76, nonce);\n"
"\n"
"    sha256_80bytes(header80, hash1);\n"
"    sha256_32bytes(hash1, hash2_be);\n"
"\n"
/* Keep the SHA256d digest bytes: the target comparator interprets them as LE. */
"    for(int i=0;i<32;++i) hash2_le[i] = hash2_be[i];\n"
"\n"
"    if(hash_le_less_than_target(hash2_le, target_le32)){\n"
"        if(atomic_cmpxchg(found_flag, 0u, 1u) == 0u){\n"
"            *found_nonce = nonce;\n"
"            for(int i=0;i<32;++i) found_hash_le32[i] = hash2_le[i];\n"
"        }\n"
"    }\n"
"\n"
"    last_nonce_out[gid] = nonce;\n"
"    hashes_done_out[gid] = 1UL;\n"
"}\n";

static void reset_result(hashscan_result_t *out) {
    if (!out) return;
    out->hashes_done = 0;
    out->last_nonce = 0;
    out->found_nonce = 0;
    out->found = 0;
    memset(out->found_hash, 0, 32);
}

static void load_opencl_devices_once(void) {
    if (g_devices_loaded) return;
    g_devices_loaded = 1;
    g_device_count = 0;

    cl_uint num_platforms = 0;
    if (clGetPlatformIDs(0, NULL, &num_platforms) != CL_SUCCESS || num_platforms == 0) {
        return;
    }

    cl_platform_id *platforms = (cl_platform_id *)calloc(num_platforms, sizeof(cl_platform_id));
    if (!platforms) return;

    if (clGetPlatformIDs(num_platforms, platforms, NULL) != CL_SUCCESS) {
        free(platforms);
        return;
    }

    for (cl_uint p = 0; p < num_platforms && g_device_count < 32; ++p) {
        cl_uint num_devices = 0;
        cl_int rc = clGetDeviceIDs(platforms[p], CL_DEVICE_TYPE_GPU, 0, NULL, &num_devices);
        if (rc != CL_SUCCESS || num_devices == 0) continue;

        cl_device_id *devices = (cl_device_id *)calloc(num_devices, sizeof(cl_device_id));
        if (!devices) continue;

        rc = clGetDeviceIDs(platforms[p], CL_DEVICE_TYPE_GPU, num_devices, devices, NULL);
        if (rc != CL_SUCCESS) {
            free(devices);
            continue;
        }

        for (cl_uint d = 0; d < num_devices && g_device_count < 32; ++d) {
            opencl_device_info_t *dst = &g_devices[g_device_count];
            memset(dst, 0, sizeof(*dst));
            dst->platform = platforms[p];
            dst->device = devices[d];
            dst->initialized = 1;

            size_t name_size = 0;
            if (clGetDeviceInfo(devices[d], CL_DEVICE_NAME, 0, NULL, &name_size) == CL_SUCCESS && name_size > 0) {
                char tmp[256];
                memset(tmp, 0, sizeof(tmp));
                clGetDeviceInfo(devices[d], CL_DEVICE_NAME, sizeof(tmp) - 1, tmp, NULL);
                strncpy(dst->name, tmp, sizeof(dst->name) - 1);
            } else {
                snprintf(dst->name, sizeof(dst->name), "OpenCL GPU %d", g_device_count);
            }

            g_device_count++;
        }

        free(devices);
    }

    free(platforms);
}

DLL_EXPORT int opencl_get_device_count(void) {
    load_opencl_devices_once();
    return g_device_count;
}

DLL_EXPORT int opencl_get_device_name(int device_index, char *buffer, int buffer_size) {
    load_opencl_devices_once();

    if (device_index < 0 || device_index >= g_device_count || !buffer || buffer_size <= 0) {
        return -1;
    }

    buffer[0] = '\0';
    strncpy(buffer, g_devices[device_index].name, (size_t)buffer_size - 1);
    buffer[buffer_size - 1] = '\0';
    return 0;
}

static int opencl_run_scan(
    const uint8_t *header_prefix76,
    const uint8_t *target_le32,
    int device_index,
    uint32_t start_nonce,
    uint32_t step,
    uint64_t max_hashes,
    hashscan_result_t *out
) {
    cl_int rc = CL_SUCCESS;
    cl_context context = NULL;
    cl_command_queue queue = NULL;
    cl_program program = NULL;
    cl_kernel kernel = NULL;

    cl_mem buf_header = NULL;
    cl_mem buf_target = NULL;
    cl_mem buf_found_flag = NULL;
    cl_mem buf_found_nonce = NULL;
    cl_mem buf_found_hash = NULL;
    cl_mem buf_last_nonce = NULL;
    cl_mem buf_hashes_done = NULL;

    uint32_t found_flag = 0;
    uint32_t found_nonce = 0;
    uint8_t found_hash[32];
    memset(found_hash, 0, sizeof(found_hash));

    if (!header_prefix76 || !target_le32 || !out || step == 0 || max_hashes == 0) {
        return -1;
    }

    load_opencl_devices_once();
    if (device_index < 0 || device_index >= g_device_count) {
        return -2;
    }

    const opencl_device_info_t *dev = &g_devices[device_index];

    context = clCreateContext(NULL, 1, &dev->device, NULL, NULL, &rc);
    if (rc != CL_SUCCESS || !context) goto fail;

    queue = clCreateCommandQueue(context, dev->device, 0, &rc);
    if (rc != CL_SUCCESS || !queue) goto fail;

    {
        const char *src = OPENCL_KERNEL_SRC;
        size_t src_len = strlen(src);
        program = clCreateProgramWithSource(context, 1, &src, &src_len, &rc);
        if (rc != CL_SUCCESS || !program) goto fail;

        rc = clBuildProgram(program, 1, &dev->device, "", NULL, NULL);
        if (rc != CL_SUCCESS) {
            size_t log_size = 0;
            clGetProgramBuildInfo(program, dev->device, CL_PROGRAM_BUILD_LOG, 0, NULL, &log_size);
            if (log_size > 1) {
                char *logbuf = (char *)calloc(log_size + 1, 1);
                if (logbuf) {
                    clGetProgramBuildInfo(program, dev->device, CL_PROGRAM_BUILD_LOG, log_size, logbuf, NULL);
                    fprintf(stderr, "[opencl] build log:\n%s\n", logbuf);
                    free(logbuf);
                }
            }
            goto fail;
        }
    }

    kernel = clCreateKernel(program, "opencl_scan_kernel", &rc);
    if (rc != CL_SUCCESS || !kernel) goto fail;

    buf_header = clCreateBuffer(context, CL_MEM_READ_ONLY | CL_MEM_COPY_HOST_PTR, 76, (void *)header_prefix76, &rc);
    if (rc != CL_SUCCESS) goto fail;

    buf_target = clCreateBuffer(context, CL_MEM_READ_ONLY | CL_MEM_COPY_HOST_PTR, 32, (void *)target_le32, &rc);
    if (rc != CL_SUCCESS) goto fail;

    buf_found_flag = clCreateBuffer(context, CL_MEM_READ_WRITE | CL_MEM_COPY_HOST_PTR, sizeof(found_flag), &found_flag, &rc);
    if (rc != CL_SUCCESS) goto fail;

    buf_found_nonce = clCreateBuffer(context, CL_MEM_READ_WRITE | CL_MEM_COPY_HOST_PTR, sizeof(found_nonce), &found_nonce, &rc);
    if (rc != CL_SUCCESS) goto fail;

    buf_found_hash = clCreateBuffer(context, CL_MEM_READ_WRITE | CL_MEM_COPY_HOST_PTR, 32, found_hash, &rc);
    if (rc != CL_SUCCESS) goto fail;

    buf_last_nonce = clCreateBuffer(context, CL_MEM_READ_WRITE, (size_t)(sizeof(uint32_t) * max_hashes), NULL, &rc);
    if (rc != CL_SUCCESS) goto fail;

    buf_hashes_done = clCreateBuffer(context, CL_MEM_READ_WRITE, (size_t)(sizeof(uint64_t) * max_hashes), NULL, &rc);
    if (rc != CL_SUCCESS) goto fail;

    rc  = clSetKernelArg(kernel, 0, sizeof(cl_mem), &buf_header);
    rc |= clSetKernelArg(kernel, 1, sizeof(cl_mem), &buf_target);
    rc |= clSetKernelArg(kernel, 2, sizeof(uint32_t), &start_nonce);
    rc |= clSetKernelArg(kernel, 3, sizeof(uint32_t), &step);
    rc |= clSetKernelArg(kernel, 4, sizeof(uint64_t), &max_hashes);
    rc |= clSetKernelArg(kernel, 5, sizeof(cl_mem), &buf_found_flag);
    rc |= clSetKernelArg(kernel, 6, sizeof(cl_mem), &buf_found_nonce);
    rc |= clSetKernelArg(kernel, 7, sizeof(cl_mem), &buf_found_hash);
    rc |= clSetKernelArg(kernel, 8, sizeof(cl_mem), &buf_last_nonce);
    rc |= clSetKernelArg(kernel, 9, sizeof(cl_mem), &buf_hashes_done);
    if (rc != CL_SUCCESS) goto fail;

    {
        size_t global_size = (size_t)max_hashes;
        rc = clEnqueueNDRangeKernel(queue, kernel, 1, NULL, &global_size, NULL, 0, NULL, NULL);
        if (rc != CL_SUCCESS) goto fail;
    }

    rc = clFinish(queue);
    if (rc != CL_SUCCESS) goto fail;

    rc  = clEnqueueReadBuffer(queue, buf_found_flag, CL_TRUE, 0, sizeof(found_flag), &found_flag, 0, NULL, NULL);
    rc |= clEnqueueReadBuffer(queue, buf_found_nonce, CL_TRUE, 0, sizeof(found_nonce), &found_nonce, 0, NULL, NULL);
    rc |= clEnqueueReadBuffer(queue, buf_found_hash, CL_TRUE, 0, 32, found_hash, 0, NULL, NULL);
    if (rc != CL_SUCCESS) goto fail;

    out->hashes_done = max_hashes;
    out->last_nonce = start_nonce + (uint32_t)((max_hashes - 1) * (uint64_t)step);
    out->found = found_flag ? 1 : 0;
    out->found_nonce = found_flag ? found_nonce : 0;
    memcpy(out->found_hash, found_hash, 32);

    clReleaseMemObject(buf_hashes_done);
    clReleaseMemObject(buf_last_nonce);
    clReleaseMemObject(buf_found_hash);
    clReleaseMemObject(buf_found_nonce);
    clReleaseMemObject(buf_found_flag);
    clReleaseMemObject(buf_target);
    clReleaseMemObject(buf_header);
    clReleaseKernel(kernel);
    clReleaseProgram(program);
    clReleaseCommandQueue(queue);
    clReleaseContext(context);
    return 0;

fail:
    if (buf_hashes_done) clReleaseMemObject(buf_hashes_done);
    if (buf_last_nonce) clReleaseMemObject(buf_last_nonce);
    if (buf_found_hash) clReleaseMemObject(buf_found_hash);
    if (buf_found_nonce) clReleaseMemObject(buf_found_nonce);
    if (buf_found_flag) clReleaseMemObject(buf_found_flag);
    if (buf_target) clReleaseMemObject(buf_target);
    if (buf_header) clReleaseMemObject(buf_header);
    if (kernel) clReleaseKernel(kernel);
    if (program) clReleaseProgram(program);
    if (queue) clReleaseCommandQueue(queue);
    if (context) clReleaseContext(context);
    return -3;
}

DLL_EXPORT int opencl_scan_nonces(
    const unsigned char *header_prefix76,
    const unsigned char *target_le32,
    int device_index,
    uint32_t start_nonce,
    uint32_t step,
    uint64_t max_hashes,
    hashscan_result_t *out
) {
    reset_result(out);
    return opencl_run_scan(
        header_prefix76,
        target_le32,
        device_index,
        start_nonce,
        step,
        max_hashes,
        out
    );
}

#include <cuda_runtime.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <stdlib.h>
#include <stdio.h>

#ifdef _WIN32
#define DLL_EXPORT extern "C" __declspec(dllexport)
#else
#define DLL_EXPORT extern "C"
#endif

struct CudaHashScanResult {
    uint64_t hashes_done;
    uint32_t last_nonce;
    uint32_t found_nonce;
    uint8_t  found;
    unsigned char found_hash[32];
};

__device__ __forceinline__ uint32_t rotr32(uint32_t x, uint32_t n) {
    return (x >> n) | (x << (32 - n));
}

__device__ __forceinline__ uint32_t ch(uint32_t x, uint32_t y, uint32_t z) {
    return (x & y) ^ (~x & z);
}

__device__ __forceinline__ uint32_t maj(uint32_t x, uint32_t y, uint32_t z) {
    return (x & y) ^ (x & z) ^ (y & z);
}

__device__ __forceinline__ uint32_t bsig0(uint32_t x) {
    return rotr32(x, 2) ^ rotr32(x, 13) ^ rotr32(x, 22);
}

__device__ __forceinline__ uint32_t bsig1(uint32_t x) {
    return rotr32(x, 6) ^ rotr32(x, 11) ^ rotr32(x, 25);
}

__device__ __forceinline__ uint32_t ssig0(uint32_t x) {
    return rotr32(x, 7) ^ rotr32(x, 18) ^ (x >> 3);
}

__device__ __forceinline__ uint32_t ssig1(uint32_t x) {
    return rotr32(x, 17) ^ rotr32(x, 19) ^ (x >> 10);
}

__device__ __constant__ uint32_t K256[64] = {
    0x428a2f98U,0x71374491U,0xb5c0fbcfU,0xe9b5dba5U,0x3956c25bU,0x59f111f1U,0x923f82a4U,0xab1c5ed5U,
    0xd807aa98U,0x12835b01U,0x243185beU,0x550c7dc3U,0x72be5d74U,0x80deb1feU,0x9bdc06a7U,0xc19bf174U,
    0xe49b69c1U,0xefbe4786U,0x0fc19dc6U,0x240ca1ccU,0x2de92c6fU,0x4a7484aaU,0x5cb0a9dcU,0x76f988daU,
    0x983e5152U,0xa831c66dU,0xb00327c8U,0xbf597fc7U,0xc6e00bf3U,0xd5a79147U,0x06ca6351U,0x14292967U,
    0x27b70a85U,0x2e1b2138U,0x4d2c6dfcU,0x53380d13U,0x650a7354U,0x766a0abbU,0x81c2c92eU,0x92722c85U,
    0xa2bfe8a1U,0xa81a664bU,0xc24b8b70U,0xc76c51a3U,0xd192e819U,0xd6990624U,0xf40e3585U,0x106aa070U,
    0x19a4c116U,0x1e376c08U,0x2748774cU,0x34b0bcb5U,0x391c0cb3U,0x4ed8aa4aU,0x5b9cca4fU,0x682e6ff3U,
    0x748f82eeU,0x78a5636fU,0x84c87814U,0x8cc70208U,0x90befffaU,0xa4506cebU,0xbef9a3f7U,0xc67178f2U
};

__device__ void sha256_compress(const unsigned char block[64], uint32_t state[8]) {
    uint32_t w[64];
    #pragma unroll
    for (int i = 0; i < 16; ++i) {
        int j = i * 4;
        w[i] = ((uint32_t)block[j] << 24) | ((uint32_t)block[j + 1] << 16) | ((uint32_t)block[j + 2] << 8) | ((uint32_t)block[j + 3]);
    }
    #pragma unroll
    for (int i = 16; i < 64; ++i) {
        w[i] = ssig1(w[i - 2]) + w[i - 7] + ssig0(w[i - 15]) + w[i - 16];
    }

    uint32_t a = state[0], b = state[1], c = state[2], d = state[3];
    uint32_t e = state[4], f = state[5], g = state[6], h = state[7];

    #pragma unroll
    for (int i = 0; i < 64; ++i) {
        uint32_t t1 = h + bsig1(e) + ch(e, f, g) + K256[i] + w[i];
        uint32_t t2 = bsig0(a) + maj(a, b, c);
        h = g; g = f; f = e; e = d + t1;
        d = c; c = b; b = a; a = t1 + t2;
    }

    state[0] += a; state[1] += b; state[2] += c; state[3] += d;
    state[4] += e; state[5] += f; state[6] += g; state[7] += h;
}

__device__ void sha256_bytes(const unsigned char* data, int len, unsigned char out[32]) {
    uint32_t state[8] = {
        0x6a09e667U,0xbb67ae85U,0x3c6ef372U,0xa54ff53aU,
        0x510e527fU,0x9b05688cU,0x1f83d9abU,0x5be0cd19U
    };
    unsigned char block[64];
    int full = len / 64;
    for (int i = 0; i < full; ++i) {
        sha256_compress(data + (i * 64), state);
    }
    int rem = len % 64;
    memset(block, 0, 64);
    if (rem > 0) memcpy(block, data + (full * 64), rem);
    block[rem] = 0x80;
    if (rem >= 56) {
        sha256_compress(block, state);
        memset(block, 0, 64);
    }
    uint64_t bitlen = (uint64_t)len * 8ULL;
    for (int i = 0; i < 8; ++i) {
        block[63 - i] = (unsigned char)((bitlen >> (i * 8)) & 0xffU);
    }
    sha256_compress(block, state);
    for (int i = 0; i < 8; ++i) {
        out[i * 4 + 0] = (unsigned char)((state[i] >> 24) & 0xffU);
        out[i * 4 + 1] = (unsigned char)((state[i] >> 16) & 0xffU);
        out[i * 4 + 2] = (unsigned char)((state[i] >> 8) & 0xffU);
        out[i * 4 + 3] = (unsigned char)(state[i] & 0xffU);
    }
}

__device__ void sha256d_80(const unsigned char header80[80], unsigned char out_le[32]) {
    unsigned char first[32];
    unsigned char second[32];
    sha256_bytes(header80, 80, first);
    sha256_bytes(first, 32, second);
    #pragma unroll
    for (int i = 0; i < 32; ++i) {
        out_le[i] = second[i];
    }
}

__device__ bool hash_le_less_than_target(const unsigned char hash_le[32], const unsigned char target_le[32]) {
    for (int i = 31; i >= 0; --i) {
        if (hash_le[i] < target_le[i]) return true;
        if (hash_le[i] > target_le[i]) return false;
    }
    return true;
}

__global__ void scan_kernel(const unsigned char* header_prefix76,
                            const unsigned char* target_le32,
                            uint32_t start_nonce,
                            uint32_t step,
                            uint64_t max_hashes,
                            int* found_flag,
                            uint32_t* found_nonce,
                            unsigned char* found_hash_le) {
    uint64_t tid = (uint64_t)blockIdx.x * blockDim.x + threadIdx.x;
    uint64_t stride = (uint64_t)gridDim.x * blockDim.x;

    unsigned char header[80];
    #pragma unroll
    for (int i = 0; i < 76; ++i) header[i] = header_prefix76[i];

    for (uint64_t idx = tid; idx < max_hashes; idx += stride) {
        if (atomicAdd(found_flag, 0) != 0) return;
        uint32_t nonce = start_nonce + (uint32_t)(idx * (uint64_t)step);
        header[76] = (unsigned char)(nonce & 0xffU);
        header[77] = (unsigned char)((nonce >> 8) & 0xffU);
        header[78] = (unsigned char)((nonce >> 16) & 0xffU);
        header[79] = (unsigned char)((nonce >> 24) & 0xffU);

        unsigned char hash_le[32];
        sha256d_80(header, hash_le);
        if (hash_le_less_than_target(hash_le, target_le32)) {
            if (atomicCAS(found_flag, 0, 1) == 0) {
                *found_nonce = nonce;
                for (int j = 0; j < 32; ++j) found_hash_le[j] = hash_le[j];
            }
            return;
        }
    }
}

DLL_EXPORT int cuda_get_device_count() {
    cudaError_t err;

    int runtime_version = 0;
    int driver_version = 0;

    cudaError_t err_rt = cudaRuntimeGetVersion(&runtime_version);
    cudaError_t err_drv = cudaDriverGetVersion(&driver_version);

    fprintf(stderr, "[cuda.dll] cudaRuntimeGetVersion err=%d version=%d\n", (int)err_rt, runtime_version);
    fprintf(stderr, "[cuda.dll] cudaDriverGetVersion  err=%d version=%d\n", (int)err_drv, driver_version);

    err = cudaFree(0);
    if (err != cudaSuccess) {
        fprintf(stderr, "[cuda.dll] cudaFree(0) fallo: code=%d msg=%s\n",
                (int)err,
                cudaGetErrorString(err) ? cudaGetErrorString(err) : "(null)");
        return 0;
    }

    int count = 0;
    err = cudaGetDeviceCount(&count);
    if (err != cudaSuccess) {
        fprintf(stderr, "[cuda.dll] cudaGetDeviceCount fallo: code=%d msg=%s\n",
                (int)err,
                cudaGetErrorString(err) ? cudaGetErrorString(err) : "(null)");
        return 0;
    }

    fprintf(stderr, "[cuda.dll] cudaGetDeviceCount OK, count=%d\n", count);
    return count;
}

DLL_EXPORT int cuda_get_device_name(int index, char* out, int out_len) {
    if (!out || out_len <= 0) return -1;
    cudaDeviceProp prop;
    cudaError_t err = cudaGetDeviceProperties(&prop, index);
    if (err != cudaSuccess) return -2;
    int n = 0;
    while (prop.name[n] && n < out_len - 1) {
        out[n] = prop.name[n];
        ++n;
    }
    out[n] = '\0';
    return 0;
}

DLL_EXPORT int cuda_scan_nonces(const unsigned char* header_prefix76,
                                const unsigned char* target_le32,
                                int device_index,
                                uint32_t start_nonce,
                                uint32_t step,
                                uint64_t max_hashes,
                                CudaHashScanResult* out) {
    if (!header_prefix76 || !target_le32 || !out) return -1;
    memset(out, 0, sizeof(*out));
    out->hashes_done = max_hashes;
    if (max_hashes == 0) return 0;

    int device_count = 0;
    cudaError_t err = cudaGetDeviceCount(&device_count);
    if (err != cudaSuccess || device_count <= 0) return -2;
	
	if (device_index < 0 || device_index >= device_count) return -3;

	err = cudaSetDevice(device_index);
	if (err != cudaSuccess) return -4;

	cudaDeviceProp prop;
	err = cudaGetDeviceProperties(&prop, device_index);
	if (err != cudaSuccess) return -5;

    unsigned char *d_header = nullptr, *d_target = nullptr, *d_hash = nullptr;
    int *d_found_flag = nullptr;
    uint32_t *d_found_nonce = nullptr;

    err = cudaMalloc((void**)&d_header, 76);
	if (err != cudaSuccess) return -6;
    err = cudaMalloc((void**)&d_target, 32);
    if (err != cudaSuccess) { cudaFree(d_header); return -6; }
    err = cudaMalloc((void**)&d_hash, 32);
    if (err != cudaSuccess) { cudaFree(d_header); cudaFree(d_target); return -7; }
    err = cudaMalloc((void**)&d_found_flag, sizeof(int));
    if (err != cudaSuccess) { cudaFree(d_header); cudaFree(d_target); cudaFree(d_hash); return -8; }
    err = cudaMalloc((void**)&d_found_nonce, sizeof(uint32_t));
    if (err != cudaSuccess) { cudaFree(d_header); cudaFree(d_target); cudaFree(d_hash); cudaFree(d_found_flag); return -9; }

    int zero = 0;
    uint32_t zero_nonce = 0;
    cudaMemcpy(d_header, header_prefix76, 76, cudaMemcpyHostToDevice);
    cudaMemcpy(d_target, target_le32, 32, cudaMemcpyHostToDevice);
    cudaMemcpy(d_found_flag, &zero, sizeof(int), cudaMemcpyHostToDevice);
    cudaMemcpy(d_found_nonce, &zero_nonce, sizeof(uint32_t), cudaMemcpyHostToDevice);

    int threads = 256;
    int blocks = prop.multiProcessorCount * 8;
    uint64_t needed_blocks = (max_hashes + threads - 1ULL) / threads;
    if ((uint64_t)blocks > needed_blocks) blocks = (int)needed_blocks;
    if (blocks < 1) blocks = 1;

    scan_kernel<<<blocks, threads>>>(d_header, d_target, start_nonce, step, max_hashes, d_found_flag, d_found_nonce, d_hash);
    err = cudaDeviceSynchronize();
    if (err != cudaSuccess) {
        cudaFree(d_header); cudaFree(d_target); cudaFree(d_hash); cudaFree(d_found_flag); cudaFree(d_found_nonce);
        return -10;
    }

    int found_flag = 0;
    cudaMemcpy(&found_flag, d_found_flag, sizeof(int), cudaMemcpyDeviceToHost);
    out->last_nonce = start_nonce + (uint32_t)((max_hashes - 1ULL) * (uint64_t)step);
    if (found_flag) {
        out->found = 1;
        cudaMemcpy(&out->found_nonce, d_found_nonce, sizeof(uint32_t), cudaMemcpyDeviceToHost);
        cudaMemcpy(out->found_hash, d_hash, 32, cudaMemcpyDeviceToHost);
    }

    cudaFree(d_header); cudaFree(d_target); cudaFree(d_hash); cudaFree(d_found_flag); cudaFree(d_found_nonce);
    return 0;
}

#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <stdlib.h>

#ifdef _WIN32
#define DLL_EXPORT __declspec(dllexport)
#include <windows.h>
typedef HANDLE thread_handle_t;
typedef CRITICAL_SECTION mutex_t;
static void mutex_init(mutex_t *m){ InitializeCriticalSection(m); }
static void mutex_destroy(mutex_t *m){ DeleteCriticalSection(m); }
static void mutex_lock(mutex_t *m){ EnterCriticalSection(m); }
static void mutex_unlock(mutex_t *m){ LeaveCriticalSection(m); }
#else
#define DLL_EXPORT __attribute__((visibility("default")))
#include <pthread.h>
typedef pthread_t thread_handle_t;
typedef pthread_mutex_t mutex_t;
static void mutex_init(mutex_t *m){ pthread_mutex_init(m, NULL); }
static void mutex_destroy(mutex_t *m){ pthread_mutex_destroy(m); }
static void mutex_lock(mutex_t *m){ pthread_mutex_lock(m); }
static void mutex_unlock(mutex_t *m){ pthread_mutex_unlock(m); }
#endif

typedef struct {
    uint64_t hashes_done;
    uint32_t last_nonce;
    uint32_t found_nonce;
    uint8_t found;
    uint8_t found_hash[32];
} hashscan_result_t;

typedef struct {
    const uint8_t *header_prefix76;
    const uint8_t *target_le32;
    uint32_t start_nonce;
    uint32_t step;
    uint64_t max_hashes;
    hashscan_result_t *result;
} scan_input_t;

static const uint32_t K[64] = {
    0x428a2f98U,0x71374491U,0xb5c0fbcfU,0xe9b5dba5U,0x3956c25bU,0x59f111f1U,0x923f82a4U,0xab1c5ed5U,
    0xd807aa98U,0x12835b01U,0x243185beU,0x550c7dc3U,0x72be5d74U,0x80deb1feU,0x9bdc06a7U,0xc19bf174U,
    0xe49b69c1U,0xefbe4786U,0x0fc19dc6U,0x240ca1ccU,0x2de92c6fU,0x4a7484aaU,0x5cb0a9dcU,0x76f988daU,
    0x983e5152U,0xa831c66dU,0xb00327c8U,0xbf597fc7U,0xc6e00bf3U,0xd5a79147U,0x06ca6351U,0x14292967U,
    0x27b70a85U,0x2e1b2138U,0x4d2c6dfcU,0x53380d13U,0x650a7354U,0x766a0abbU,0x81c2c92eU,0x92722c85U,
    0xa2bfe8a1U,0xa81a664bU,0xc24b8b70U,0xc76c51a3U,0xd192e819U,0xd6990624U,0xf40e3585U,0x106aa070U,
    0x19a4c116U,0x1e376c08U,0x2748774cU,0x34b0bcb5U,0x391c0cb3U,0x4ed8aa4aU,0x5b9cca4fU,0x682e6ff3U,
    0x748f82eeU,0x78a5636fU,0x84c87814U,0x8cc70208U,0x90befffaU,0xa4506cebU,0xbef9a3f7U,0xc67178f2U
};

static const uint32_t H0[8] = {
    0x6a09e667U,0xbb67ae85U,0x3c6ef372U,0xa54ff53aU,
    0x510e527fU,0x9b05688cU,0x1f83d9abU,0x5be0cd19U
};

static inline uint32_t rotr32(uint32_t x, int n){ return (x >> n) | (x << (32 - n)); }
static inline uint32_t Ch(uint32_t x, uint32_t y, uint32_t z){ return (x & y) ^ (~x & z); }
static inline uint32_t Maj(uint32_t x, uint32_t y, uint32_t z){ return (x & y) ^ (x & z) ^ (y & z); }
static inline uint32_t BSIG0(uint32_t x){ return rotr32(x,2) ^ rotr32(x,13) ^ rotr32(x,22); }
static inline uint32_t BSIG1(uint32_t x){ return rotr32(x,6) ^ rotr32(x,11) ^ rotr32(x,25); }
static inline uint32_t SSIG0(uint32_t x){ return rotr32(x,7) ^ rotr32(x,18) ^ (x >> 3); }
static inline uint32_t SSIG1(uint32_t x){ return rotr32(x,17) ^ rotr32(x,19) ^ (x >> 10); }
static inline uint32_t load_be32(const uint8_t *p){ return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) | ((uint32_t)p[2] << 8) | (uint32_t)p[3]; }
static inline void store_be32(uint8_t *p, uint32_t v){ p[0]=(uint8_t)(v>>24); p[1]=(uint8_t)(v>>16); p[2]=(uint8_t)(v>>8); p[3]=(uint8_t)v; }
static inline void store_le32(uint8_t *p, uint32_t v){ p[0]=(uint8_t)v; p[1]=(uint8_t)(v>>8); p[2]=(uint8_t)(v>>16); p[3]=(uint8_t)(v>>24); }

static void sha256_compress(uint32_t state[8], const uint8_t block[64]) {
    uint32_t W[64];
    for (int i = 0; i < 16; ++i) W[i] = load_be32(block + i*4);
    for (int i = 16; i < 64; ++i) W[i] = SSIG1(W[i-2]) + W[i-7] + SSIG0(W[i-15]) + W[i-16];

    uint32_t a=state[0], b=state[1], c=state[2], d=state[3], e=state[4], f=state[5], g=state[6], h=state[7];
    for (int i = 0; i < 64; ++i) {
        uint32_t t1 = h + BSIG1(e) + Ch(e,f,g) + K[i] + W[i];
        uint32_t t2 = BSIG0(a) + Maj(a,b,c);
        h = g; g = f; f = e; e = d + t1;
        d = c; c = b; b = a; a = t1 + t2;
    }
    state[0] += a; state[1] += b; state[2] += c; state[3] += d;
    state[4] += e; state[5] += f; state[6] += g; state[7] += h;
}

/* Prepares the state after hashing the first 64 bytes of the 80-byte header. */
static void sha256_midstate_64(const uint8_t first64[64], uint32_t mid[8]) {
    for (int i = 0; i < 8; ++i) mid[i] = H0[i];
    sha256_compress(mid, first64);
}

/* Compute SHA256(header80) from a precomputed midstate after first 64 bytes. */
static void sha256_header80_from_midstate(const uint32_t mid[8], const uint8_t tail16[16], uint8_t out32[32]) {
    uint8_t block[64];
    uint32_t state[8];
    memcpy(state, mid, 32);
    memset(block, 0, 64);
    memcpy(block, tail16, 16);
    block[16] = 0x80;
    /* total length = 80 bytes = 640 bits */
    block[62] = 0x02;
    block[63] = 0x80;
    sha256_compress(state, block);
    for (int i = 0; i < 8; ++i) store_be32(out32 + i*4, state[i]);
}

/* Specialized SHA256 for a 32-byte input (single block message). */
static void sha256_32bytes(const uint8_t in32[32], uint8_t out32[32]) {
    uint8_t block[64];
    uint32_t state[8];
    memcpy(state, H0, sizeof(H0));
    memset(block, 0, 64);
    memcpy(block, in32, 32);
    block[32] = 0x80;
    block[62] = 0x01; /* 32 bytes = 256 bits */
    block[63] = 0x00;
    sha256_compress(state, block);
    for (int i = 0; i < 8; ++i) store_be32(out32 + i*4, state[i]);
}

static int hash_le_less_than_target(const uint8_t hash_le32[32], const uint8_t target_le32[32]) {
    /* Both hash and target are interpreted as 256-bit little-endian integers. */
    for (int i = 31; i >= 0; --i) {
        uint8_t h = hash_le32[i];
        uint8_t t = target_le32[i];
        if (h < t) return 1;
        if (h > t) return 0;
    }
    return 1; /* equal also satisfies PoW */
}

static int scan_nonces_core(const uint8_t *header_prefix76,
                            const uint8_t *target_le32,
                            uint32_t start_nonce,
                            uint32_t step,
                            uint64_t max_hashes,
                            hashscan_result_t *result,
                            volatile int *stop_flag) {
    uint32_t mid[8];
    uint8_t tail16[16];
    uint8_t hash1[32];
    uint8_t hash2[32];
    uint64_t done = 0;
    uint32_t nonce = start_nonce;
    uint32_t last_nonce = start_nonce;

    sha256_midstate_64(header_prefix76, mid);
    memcpy(tail16, header_prefix76 + 64, 12);

    while (done < max_hashes) {
        if (stop_flag && *stop_flag) break;
        store_le32(tail16 + 12, nonce);
        sha256_header80_from_midstate(mid, tail16, hash1);
        sha256_32bytes(hash1, hash2);

        last_nonce = nonce;
        done++;

        if (hash_le_less_than_target(hash2, target_le32)) {
            result->hashes_done = done;
            result->last_nonce = last_nonce;
            result->found_nonce = nonce;
            result->found = 1;
            for (int i = 0; i < 32; ++i) result->found_hash[i] = hash2[i];
            if (stop_flag) *stop_flag = 1;
            return 0;
        }

        nonce += step;
        if (nonce < start_nonce) break; /* wraparound */
    }

    result->hashes_done = done;
    result->last_nonce = last_nonce;
    result->found_nonce = 0;
    result->found = 0;
    memset(result->found_hash, 0, 32);
    return 0;
}

DLL_EXPORT int scan_nonces(const uint8_t *header_prefix76,
                           const uint8_t *target_le32,
                           uint32_t start_nonce,
                           uint32_t step,
                           uint64_t max_hashes,
                           hashscan_result_t *result) {
    if (!header_prefix76 || !target_le32 || !result || step == 0) return -1;
    return scan_nonces_core(header_prefix76, target_le32, start_nonce, step, max_hashes, result, NULL);
}

typedef struct {
    const uint8_t *header_prefix76;
    const uint8_t *target_le32;
    uint32_t start_nonce;
    uint32_t step;
    uint64_t max_hashes;
    volatile int *stop_flag;
    hashscan_result_t local;
} worker_ctx_t;

#ifdef _WIN32
static DWORD WINAPI thread_main(LPVOID p) {
    worker_ctx_t *ctx = (worker_ctx_t *)p;
    scan_nonces_core(ctx->header_prefix76, ctx->target_le32, ctx->start_nonce, ctx->step, ctx->max_hashes, &ctx->local, ctx->stop_flag);
    return 0;
}
#else
static void *thread_main(void *p) {
    worker_ctx_t *ctx = (worker_ctx_t *)p;
    scan_nonces_core(ctx->header_prefix76, ctx->target_le32, ctx->start_nonce, ctx->step, ctx->max_hashes, &ctx->local, ctx->stop_flag);
    return NULL;
}
#endif

DLL_EXPORT int scan_nonces_mt(const uint8_t *header_prefix76,
                              const uint8_t *target_le32,
                              uint32_t base_start_nonce,
                              uint32_t total_step,
                              uint64_t max_hashes_total,
                              uint32_t num_threads,
                              hashscan_result_t *result) {
    if (!header_prefix76 || !target_le32 || !result || num_threads == 0 || total_step == 0) return -1;

    worker_ctx_t *ctxs = (worker_ctx_t *)calloc(num_threads, sizeof(worker_ctx_t));
    thread_handle_t *threads = (thread_handle_t *)calloc(num_threads, sizeof(thread_handle_t));
    if (!ctxs || !threads) {
        free(ctxs);
        free(threads);
        return -2;
    }

    volatile int stop_flag = 0;
    uint32_t launched_threads = 0;
    uint64_t base_share = max_hashes_total / num_threads;
    uint64_t remainder = max_hashes_total % num_threads;

    for (uint32_t i = 0; i < num_threads; ++i) {
        uint64_t share = base_share + (i < remainder ? 1ULL : 0ULL);
        if (share == 0) {
            memset(&ctxs[i].local, 0, sizeof(hashscan_result_t));
            continue;
        }
        ctxs[i].header_prefix76 = header_prefix76;
        ctxs[i].target_le32 = target_le32;
        ctxs[i].start_nonce = base_start_nonce + (i * total_step);
        ctxs[i].step = total_step * num_threads;
        ctxs[i].max_hashes = share;
        ctxs[i].stop_flag = &stop_flag;
        memset(&ctxs[i].local, 0, sizeof(hashscan_result_t));
#ifdef _WIN32
        threads[i] = CreateThread(NULL, 0, thread_main, &ctxs[i], 0, NULL);
        if (!threads[i]) { stop_flag = 1; break; }
#else
        if (pthread_create(&threads[i], NULL, thread_main, &ctxs[i]) != 0) { stop_flag = 1; break; }
#endif
        launched_threads++;
    }

    for (uint32_t i = 0; i < launched_threads; ++i) {
#ifdef _WIN32
        WaitForSingleObject(threads[i], INFINITE);
        CloseHandle(threads[i]);
#else
        pthread_join(threads[i], NULL);
#endif
    }

    memset(result, 0, sizeof(*result));
    uint32_t best_last = base_start_nonce;
    int best_last_set = 0;
    for (uint32_t i = 0; i < num_threads; ++i) {
        result->hashes_done += ctxs[i].local.hashes_done;
        if (ctxs[i].local.hashes_done > 0 && (!best_last_set || ctxs[i].local.last_nonce > best_last)) {
            best_last = ctxs[i].local.last_nonce;
            best_last_set = 1;
        }
        if (ctxs[i].local.found && !result->found) {
            result->found = 1;
            result->found_nonce = ctxs[i].local.found_nonce;
            memcpy(result->found_hash, ctxs[i].local.found_hash, 32);
        }
    }
    result->last_nonce = best_last_set ? best_last : base_start_nonce;

    free(ctxs);
    free(threads);
    return 0;
}

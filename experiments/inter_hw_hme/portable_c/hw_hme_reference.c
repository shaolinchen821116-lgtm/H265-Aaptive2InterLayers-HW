#include "hw_hme_reference.h"

#include <limits.h>
#include <stdlib.h>
#include <string.h>

static int max_i(int a, int b) { return a > b ? a : b; }
static int min_i(int a, int b) { return a < b ? a : b; }

static hw_hme_mv mv_scale(hw_hme_mv mv, int scale)
{
    hw_hme_mv out = { mv.x * scale, mv.y * scale };
    return out;
}

static int mv_manhattan(hw_hme_mv mv)
{
    return abs(mv.x) + abs(mv.y);
}

static int better(uint64_t cost, uint32_t sad, hw_hme_mv mv,
                  uint64_t best_cost, uint32_t best_sad, hw_hme_mv best_mv)
{
    if (cost != best_cost) return cost < best_cost;
    if (sad != best_sad) return sad < best_sad;
    if (mv_manhattan(mv) != mv_manhattan(best_mv))
        return mv_manhattan(mv) < mv_manhattan(best_mv);
    if (mv.y != best_mv.y) return mv.y < best_mv.y;
    return mv.x < best_mv.x;
}

static int better_pme(uint64_t cost, uint32_t sad, uint32_t bits,
                      hw_hme_mv mv, uint64_t best_cost,
                      uint32_t best_sad, uint32_t best_bits,
                      hw_hme_mv best_mv)
{
    if (cost != best_cost) return cost < best_cost;
    if (sad != best_sad) return sad < best_sad;
    if (bits != best_bits) return bits < best_bits;
    if (mv_manhattan(mv) != mv_manhattan(best_mv))
        return mv_manhattan(mv) < mv_manhattan(best_mv);
    if (mv.y != best_mv.y) return mv.y < best_mv.y;
    return mv.x < best_mv.x;
}

static uint32_t sad_u8(const uint8_t* a, ptrdiff_t a_stride,
                       const uint8_t* b, ptrdiff_t b_stride,
                       int width, int height)
{
    uint32_t sad = 0;
    int x, y;
    for (y = 0; y < height; ++y)
    {
        for (x = 0; x < width; ++x)
            sad += (uint32_t)abs((int)a[x] - (int)b[x]);
        a += a_stride;
        b += b_stride;
    }
    return sad;
}

static uint32_t mean_gradient_u8(const uint8_t* src, ptrdiff_t stride,
                                 int width, int height)
{
    uint32_t sum = 0;
    uint32_t edges = 0;
    int x, y;
    for (y = 0; y < height; ++y)
    {
        for (x = 1; x < width; ++x)
            sum += (uint32_t)abs((int)src[x] - (int)src[x - 1]);
        if (y)
            for (x = 0; x < width; ++x)
                sum += (uint32_t)abs((int)src[x] - (int)src[x - stride]);
        edges += (uint32_t)(width - 1) + (y ? (uint32_t)width : 0u);
        src += stride;
    }
    return edges ? (sum + (edges >> 1)) / edges : 0;
}

void hw_hme_config_default(hw_hme_config* config)
{
    if (!config) return;
    memset(config, 0, sizeof(*config));
    config->pme_range_x_ds = 32;
    config->pme_range_y_ds = 28;
    config->ime_range_x_full = 12;
    config->ime_range_y_full = 12;
    config->pme_sad_shift = 3;
    config->pme_cost_mode = 1;
    config->pme_rate_scale_q8 = 256;
    config->pme_texture_low = 8;
    config->pme_texture_high = 24;
    config->pme_texture_weight_q8[0] = 256;
    config->pme_texture_weight_q8[1] = 160;
    config->pme_texture_weight_q8[2] = 96;
    config->pme_attractor = 1;
}

uint32_t hw_hme_default_lambda_q8(int qp)
{
    static const uint32_t table[52] = {
        64,72,81,91,102,114,128,144,161,181,203,228,256,
        287,323,362,406,456,512,575,645,724,813,912,1024,
        1149,1290,1448,1625,1825,2048,2299,2580,2896,3251,
        3649,4096,4598,5161,5793,6502,7298,8192,9195,10321,
        11585,13004,14596,16384,18390,20643,23170
    };
    if (qp < 0) qp = 0;
    if (qp > 51) qp = 51;
    return table[qp];
}

static uint8_t filter2x2(const uint8_t* src, ptrdiff_t stride)
{
    unsigned ab = ((unsigned)src[0] + src[stride] + 1u) >> 1;
    unsigned cd = ((unsigned)src[1] + src[stride + 1] + 1u) >> 1;
    return (uint8_t)((ab + cd + 1u) >> 1);
}

static void downsample2(const uint8_t* src, ptrdiff_t src_stride,
                        int dst_width, int dst_height, uint8_t* dst,
                        ptrdiff_t dst_stride)
{
    int x, y;
    for (y = 0; y < dst_height; ++y)
    {
        for (x = 0; x < dst_width; ++x)
            dst[x] = filter2x2(src + 2 * x, src_stride);
        src += 2 * src_stride;
        dst += dst_stride;
    }
}

int hw_hme_downsample4(const uint8_t* src, ptrdiff_t src_stride,
                       int width, int height, uint8_t* half_scratch,
                       ptrdiff_t half_stride, uint8_t* dst4,
                       ptrdiff_t dst4_stride)
{
    if (!src || !half_scratch || !dst4 || width <= 0 || height <= 0 ||
        (width & 3) || (height & 3) || half_stride < width / 2 ||
        dst4_stride < width / 4)
        return -1;
    downsample2(src, src_stride, width / 2, height / 2,
                half_scratch, half_stride);
    downsample2(half_scratch, half_stride, width / 4, height / 4,
                dst4, dst4_stride);
    return 0;
}

static unsigned unsigned_code_bits(uint32_t value)
{
    unsigned log2 = 0;
    uint32_t code_num = value + 1;
    while (code_num >>= 1) ++log2;
    return 2 * log2 + 1;
}

uint32_t hw_hme_default_mvd_bits(void* opaque, hw_hme_mv mv_qpel,
                                hw_hme_mv predictor_qpel)
{
    int dx = mv_qpel.x - predictor_qpel.x;
    int dy = mv_qpel.y - predictor_qpel.y;
    uint32_t map_x = dx == 0 ? 0u : (uint32_t)(2 * abs(dx) - (dx > 0));
    uint32_t map_y = dy == 0 ? 0u : (uint32_t)(2 * abs(dy) - (dy > 0));
    (void)opaque;
    return unsigned_code_bits(map_x) + unsigned_code_bits(map_y);
}

int hw_hme_search(const hw_hme_config* c, const hw_hme_input* in,
                  const hw_hme_callbacks* cb, hw_hme_result* out)
{
    static const int8_t ring[8][2] = {
        { 0,-1 }, { 1,-1 }, { 1, 0 }, { 1, 1 },
        { 0, 1 }, {-1, 1 }, {-1, 0 }, {-1,-1 }
    };
    hw_hme_mv zero = { 0, 0 };
    hw_hme_mv best_pme = { 0, 0 };
    hw_hme_mv best_ime;
    hw_hme_mv best_qpel;
    uint64_t best_pme_cost = UINT64_MAX;
    uint32_t best_pme_sad = UINT_MAX, best_pme_bits = UINT_MAX;
    uint64_t best_ime_cost = UINT64_MAX, best_fme_cost;
    uint32_t best_ime_sad = UINT_MAX, best_fme_sad;
    uint32_t activity, lambda_q8, texture_weight_q8;
    uint64_t combined_weight;
    int ds_size, bx_ds, by_ds, dx, dy, x, y, i, step;
    const uint8_t* cur_ds;
    const uint8_t* ref_ds;
    const uint8_t* cur_full;
    const uint8_t* ref_full;

    if (!c || !in || !cb || !out || !cb->mvd_bits || !cb->mvd_cost ||
        !cb->qpel_sad || (in->block_size != 8 && in->block_size != 16 &&
        in->block_size != 32) || c->pme_sad_shift > 15 ||
        c->pme_cost_mode < 0 || c->pme_cost_mode > 1 ||
        c->pme_attractor < 0 || c->pme_attractor > 2)
        return -1;
    memset(out, 0, sizeof(*out));
    ds_size = in->block_size / 4;
    bx_ds = in->block_x_full / 4;
    by_ds = in->block_y_full / 4;
    cur_ds = in->current_ds4.data + by_ds * in->current_ds4.stride + bx_ds;
    ref_ds = in->reference_ds4.data + by_ds * in->reference_ds4.stride + bx_ds;
    cur_full = in->current_full.data + in->block_y_full * in->current_full.stride + in->block_x_full;
    ref_full = in->reference_full.data + in->block_y_full * in->reference_full.stride + in->block_x_full;

    activity = mean_gradient_u8(cur_ds, in->current_ds4.stride,
                                ds_size, ds_size);
    out->pme_texture_class = (uint8_t)(activity < c->pme_texture_low ? 0 :
        (activity < c->pme_texture_high ? 1 : 2));
    texture_weight_q8 = c->pme_texture_weight_q8[out->pme_texture_class];
    lambda_q8 = hw_hme_default_lambda_q8(in->qp);
    combined_weight = (uint64_t)lambda_q8 * c->pme_rate_scale_q8 *
                      texture_weight_q8;
    out->pme_activity = activity;
    out->pme_rate_weight_q8 = (uint32_t)((combined_weight + (1u << 15)) >> 16);

    /* PME motion units are integer samples on the 1/4-resolution plane. */
    for (dy = -c->pme_range_y_ds; dy <= c->pme_range_y_ds; ++dy)
    {
        int full_y = dy * 4;
        if (full_y < in->mv_min_full.y || full_y > in->mv_max_full.y ||
            by_ds + dy < 0 || by_ds + dy + ds_size > in->reference_ds4.height)
            continue;
        for (dx = -c->pme_range_x_ds; dx <= c->pme_range_x_ds; ++dx)
        {
            hw_hme_mv mv_ds = { dx, dy };
            hw_hme_mv mv_qpel = mv_scale(mv_ds, 16);
            uint32_t sad, bits, bits_zero, bits_amvp;
            uint64_t cost;
            int used_amvp = 0;
            int full_x = dx * 4;
            if (full_x < in->mv_min_full.x || full_x > in->mv_max_full.x ||
                bx_ds + dx < 0 || bx_ds + dx + ds_size > in->reference_ds4.width)
                continue;
            sad = sad_u8(cur_ds, in->current_ds4.stride,
                         ref_ds + dy * in->reference_ds4.stride + dx,
                         in->reference_ds4.stride, ds_size, ds_size);
            bits_zero = cb->mvd_bits(cb->opaque, mv_qpel, zero);
            bits_amvp = cb->mvd_bits(cb->opaque, mv_qpel, in->amvp_qpel);
            bits = bits_zero;
            if (c->pme_attractor == 1)
            {
                bits = bits_amvp;
                used_amvp = 1;
            }
            else if (c->pme_attractor == 2 && bits_amvp + 1 < bits_zero)
            {
                bits = bits_amvp + 1;
                used_amvp = 1;
            }
            if (c->pme_cost_mode == 0)
                cost = ((uint64_t)(sad >> c->pme_sad_shift)) * bits_zero;
            else
                cost = (uint64_t)sad +
                    (((uint64_t)bits * combined_weight + (1u << 23)) >> 24);
            ++out->pme_candidates;
            if (better_pme(cost, sad, bits, mv_ds, best_pme_cost,
                           best_pme_sad, best_pme_bits, best_pme))
            {
                best_pme_cost = cost;
                best_pme_sad = sad;
                best_pme_bits = bits;
                best_pme = mv_ds;
                out->pme_used_amvp = (uint8_t)used_amvp;
            }
        }
    }
    if (!out->pme_candidates) return -2;
    out->pme_mv_ds = best_pme;
    out->ime_center_full = mv_scale(best_pme, 4); /* explicit PME -> IME alignment */
    out->pme_sad = best_pme_sad;
    out->pme_bits = best_pme_bits;
    out->pme_cost = best_pme_cost;

    /* IME motion units are full-resolution integer pixels. */
    best_ime = out->ime_center_full;
    for (y = max_i(in->mv_min_full.y, out->ime_center_full.y - c->ime_range_y_full);
         y <= min_i(in->mv_max_full.y, out->ime_center_full.y + c->ime_range_y_full); ++y)
    {
        for (x = max_i(in->mv_min_full.x, out->ime_center_full.x - c->ime_range_x_full);
             x <= min_i(in->mv_max_full.x, out->ime_center_full.x + c->ime_range_x_full); ++x)
        {
            hw_hme_mv mv_full = { x, y };
            hw_hme_mv mv_qpel = mv_scale(mv_full, 4);
            uint32_t sad = sad_u8(cur_full, in->current_full.stride,
                                  ref_full + y * in->reference_full.stride + x,
                                  in->reference_full.stride,
                                  in->block_size, in->block_size);
            uint32_t cost = sad + cb->mvd_cost(cb->opaque, in->qp,
                                              mv_qpel, in->amvp_qpel);
            ++out->ime_candidates;
            if (better(cost, sad, mv_full, best_ime_cost, best_ime_sad, best_ime))
            {
                best_ime_cost = cost;
                best_ime_sad = sad;
                best_ime = mv_full;
            }
        }
    }
    if (!out->ime_candidates) return -3;
    out->ime_mv_full = best_ime;
    out->ime_sad = best_ime_sad;
    out->ime_cost = (uint32_t)best_ime_cost;

    /* FME uses qpel units: IME seed, one AMVP guard candidate, then
     * 8 half-pel and 8 quarter-pel samples around the better seed. */
    best_qpel = mv_scale(best_ime, 4);
    best_fme_sad = cb->qpel_sad(cb->opaque, best_qpel);
    best_fme_cost = best_fme_sad + cb->mvd_cost(cb->opaque, in->qp,
                                               best_qpel, in->amvp_qpel);
    out->fme_candidates = 1;
    if (in->amvp_qpel.x != best_qpel.x || in->amvp_qpel.y != best_qpel.y)
    {
        hw_hme_mv guard = in->amvp_qpel;
        uint32_t sad;
        uint32_t cost;
        guard.x = max_i(in->mv_min_full.x * 4,
                        min_i(in->mv_max_full.x * 4, guard.x));
        guard.y = max_i(in->mv_min_full.y * 4,
                        min_i(in->mv_max_full.y * 4, guard.y));
        sad = cb->qpel_sad(cb->opaque, guard);
        cost = sad + cb->mvd_cost(cb->opaque, in->qp, guard, in->amvp_qpel);
        ++out->fme_candidates;
        if (better(cost, sad, guard, best_fme_cost, best_fme_sad, best_qpel))
        {
            best_fme_cost = cost;
            best_fme_sad = sad;
            best_qpel = guard;
        }
    }
    for (step = 2; step >= 1; --step)
    {
        hw_hme_mv center = best_qpel;
        for (i = 0; i < 8; ++i)
        {
            hw_hme_mv candidate = {
                center.x + ring[i][0] * step,
                center.y + ring[i][1] * step
            };
            uint32_t sad, cost;
            if (candidate.x < in->mv_min_full.x * 4 ||
                candidate.x > in->mv_max_full.x * 4 ||
                candidate.y < in->mv_min_full.y * 4 ||
                candidate.y > in->mv_max_full.y * 4)
                continue;
            sad = cb->qpel_sad(cb->opaque, candidate);
            cost = sad + cb->mvd_cost(cb->opaque, in->qp,
                                      candidate, in->amvp_qpel);
            ++out->fme_candidates;
            if (better(cost, sad, candidate, best_fme_cost, best_fme_sad, best_qpel))
            {
                best_fme_cost = cost;
                best_fme_sad = sad;
                best_qpel = candidate;
            }
        }
    }
    out->fme_mv_qpel = best_qpel;
    out->fme_sad = best_fme_sad;
    out->fme_cost = (uint32_t)best_fme_cost;
    return 0;
}

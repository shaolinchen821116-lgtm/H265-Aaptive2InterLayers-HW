#include "hw_hme_reference.h"
#include "inter_only32_gate_model.h"
#include "inter_multiscale_gate_model.h"

#include <limits.h>
#include <stdlib.h>
#include <string.h>

static int max_i(int a, int b) { return a > b ? a : b; }
static int min_i(int a, int b) { return a < b ? a : b; }
static uint32_t abs_u32(int value) { return (uint32_t)(value < 0 ? -value : value); }

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
    out->ime_boundary = (uint8_t)(
        best_ime.x == max_i(in->mv_min_full.x, out->ime_center_full.x - c->ime_range_x_full) ||
        best_ime.x == min_i(in->mv_max_full.x, out->ime_center_full.x + c->ime_range_x_full) ||
        best_ime.y == max_i(in->mv_min_full.y, out->ime_center_full.y - c->ime_range_y_full) ||
        best_ime.y == min_i(in->mv_max_full.y, out->ime_center_full.y + c->ime_range_y_full));

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

int hw_hme_select_inter_layers(const hw_hme_result* result,
                               hw_hme_mv amvp_qpel, int qp,
                               int low2_probability_cutoff,
                               int only32_probability_cutoff,
                               hw_hme_inter_layer_decision* decision)
{
    uint32_t sad, mv, low_probability;
    hw_hme_mv ime_qpel;
    if (!result || !decision || qp < 0 || qp > 51 ||
        low2_probability_cutoff < 0 || low2_probability_cutoff > 100 ||
        only32_probability_cutoff < 0 || only32_probability_cutoff > 100)
        return -1;
    memset(decision, 0, sizeof(*decision));
    decision->layer_set = HW_HME_INTER_LOW_16_8;
    decision->features.ime_sad_per_pixel_q8 = (result->ime_sad + 2u) >> 2;
    decision->features.pme_to_ime_l1 =
        abs_u32(result->ime_mv_full.x - result->ime_center_full.x) +
        abs_u32(result->ime_mv_full.y - result->ime_center_full.y);
    ime_qpel = mv_scale(result->ime_mv_full, 4);
    decision->features.ime_mvd_qpel_l1 =
        abs_u32(ime_qpel.x - amvp_qpel.x) + abs_u32(ime_qpel.y - amvp_qpel.y);
    decision->features.ime_mv_fullpel_l1 =
        abs_u32(result->ime_mv_full.x) + abs_u32(result->ime_mv_full.y);
    decision->features.pme_activity = result->pme_activity;
    decision->features.ime_boundary = result->ime_boundary;
    decision->only32_probability = hw_hme_inter_only32_model_probability(
        qp, decision->features.ime_sad_per_pixel_q8,
        decision->features.pme_to_ime_l1,
        decision->features.ime_mvd_qpel_l1,
        decision->features.ime_mv_fullpel_l1,
        decision->features.pme_activity, decision->features.ime_boundary);
    if (decision->only32_probability >= (uint32_t)only32_probability_cutoff)
    {
        decision->layer_set = HW_HME_INTER_ONLY_32;
        return 0;
    }

    sad = decision->features.ime_sad_per_pixel_q8;
    mv = decision->features.ime_mv_fullpel_l1;
    if (qp <= 29)
    {
        if (sad <= 665)
            low_probability = qp <= 24 ? (mv <= 2 ? 79u : 67u)
                                      : (sad <= 565 ? 25u : 41u);
        else if (mv <= 4)
            low_probability = sad <= 959 ? 80u : 93u;
        else
            low_probability = qp <= 24 ? 81u : 60u;
    }
    else if (sad <= 1184)
        low_probability = sad <= 781 ? (qp <= 34 ? 18u : 10u)
                                     : (qp <= 34 ? 46u : 20u);
    else if (qp <= 34)
        low_probability = mv <= 7 ? 82u : 58u;
    else
        low_probability = sad <= 1633 ? 38u : 64u;
    decision->low2_probability = low_probability;
    decision->layer_set = low_probability >= (uint32_t)low2_probability_cutoff
                        ? HW_HME_INTER_LOW_16_8 : HW_HME_INTER_HIGH_32_16;
    return 0;
}

enum hw_hme_ms_index
{
    MS_QP = 0, MS_SAD32, MS_REFINE32, MS_MVD32, MS_MV32,
    MS_ACTIVITY32, MS_BOUNDARY32, MS_SAD16_MEAN, MS_SAD16_RANGE,
    MS_SAD16_MAD, MS_SAD8_MEAN, MS_SAD8_RANGE, MS_SAD8_MAD,
    MS_GAIN32_16, MS_GAIN16_8, MS_GAIN16_8_MAX, MS_MV16_ROOT_MEAN,
    MS_MV16_ROOT_MAX, MS_MV16_SPAN, MS_MV8_PARENT_MEAN,
    MS_MV8_PARENT_MAX, MS_MV8_ROOT_MEAN, MS_MV8_ROOT_MAX,
    MS_MV8_SPAN, MS_ACTIVITY16_MEAN, MS_ACTIVITY16_RANGE,
    MS_ACTIVITY8_MEAN, MS_ACTIVITY8_RANGE, MS_BOUNDARY_COUNT
};

static uint32_t mv_diff_l1(hw_hme_mv a, hw_hme_mv b)
{
    return abs_u32(a.x - b.x) + abs_u32(a.y - b.y);
}

int hw_hme_build_inter_scale_features(
    const hw_hme_result* root, hw_hme_mv root_amvp_qpel, int qp,
    const hw_hme_result probe16[4], const hw_hme_result probe8[16],
    int ime_range_x, int ime_range_y, hw_hme_inter_scale_features* out)
{
    uint32_t sad16[4], sad8[16];
    uint64_t sad16_sum = 0, sad8_sum = 0;
    uint64_t activity16_sum = 0, activity8_sum = 0;
    uint64_t mv16_root_sum = 0, mv8_parent_sum = 0, mv8_root_sum = 0;
    uint32_t sad16_min = UINT_MAX, sad16_max = 0;
    uint32_t sad8_min = UINT_MAX, sad8_max = 0;
    uint32_t activity16_min = UINT_MAX, activity16_max = 0;
    uint32_t activity8_min = UINT_MAX, activity8_max = 0;
    uint32_t mv16_root_max = 0, mv8_parent_max = 0, mv8_root_max = 0;
    int min16x = INT_MAX, max16x = INT_MIN, min16y = INT_MAX, max16y = INT_MIN;
    int min8x = INT_MAX, max8x = INT_MIN, min8y = INT_MAX, max8y = INT_MIN;
    uint32_t boundary_count;
    hw_hme_mv root_qpel;
    int i;
    if (!root || !probe16 || !probe8 || !out || qp < 0 || qp > 51 ||
        ime_range_x < 0 || ime_range_y < 0)
        return -1;
    memset(out, 0, sizeof(*out));
    root_qpel = mv_scale(root->ime_mv_full, 4);
    out->value[MS_QP] = (uint32_t)qp;
    out->value[MS_SAD32] = (root->ime_sad + 2u) >> 2;
    out->value[MS_REFINE32] = mv_diff_l1(root->ime_mv_full,
                                         root->ime_center_full);
    out->value[MS_MVD32] = mv_diff_l1(root_qpel, root_amvp_qpel);
    out->value[MS_MV32] = abs_u32(root->ime_mv_full.x) +
                          abs_u32(root->ime_mv_full.y);
    out->value[MS_ACTIVITY32] = root->pme_activity;
    out->value[MS_BOUNDARY32] = root->ime_boundary;
    boundary_count = root->ime_boundary;

    for (i = 0; i < 4; ++i)
    {
        uint32_t root_diff;
        sad16[i] = probe16[i].ime_sad; /* 256 pixels => raw SAD is Q8/pixel */
        sad16_sum += sad16[i];
        sad16_min = sad16[i] < sad16_min ? sad16[i] : sad16_min;
        sad16_max = sad16[i] > sad16_max ? sad16[i] : sad16_max;
        activity16_sum += probe16[i].pme_activity;
        activity16_min = probe16[i].pme_activity < activity16_min ?
                         probe16[i].pme_activity : activity16_min;
        activity16_max = probe16[i].pme_activity > activity16_max ?
                         probe16[i].pme_activity : activity16_max;
        min16x = min_i(min16x, probe16[i].ime_mv_full.x);
        max16x = max_i(max16x, probe16[i].ime_mv_full.x);
        min16y = min_i(min16y, probe16[i].ime_mv_full.y);
        max16y = max_i(max16y, probe16[i].ime_mv_full.y);
        root_diff = mv_diff_l1(probe16[i].ime_mv_full, root->ime_mv_full);
        mv16_root_sum += root_diff;
        mv16_root_max = root_diff > mv16_root_max ? root_diff : mv16_root_max;
        boundary_count +=
            abs_u32(probe16[i].ime_mv_full.x - probe16[i].ime_center_full.x) >= (uint32_t)ime_range_x ||
            abs_u32(probe16[i].ime_mv_full.y - probe16[i].ime_center_full.y) >= (uint32_t)ime_range_y;
    }
    for (i = 0; i < 16; ++i)
    {
        uint32_t parent_diff, root_diff;
        sad8[i] = probe8[i].ime_sad << 2; /* 64 pixels => SAD * 4 is Q8/pixel */
        sad8_sum += sad8[i];
        sad8_min = sad8[i] < sad8_min ? sad8[i] : sad8_min;
        sad8_max = sad8[i] > sad8_max ? sad8[i] : sad8_max;
        activity8_sum += probe8[i].pme_activity;
        activity8_min = probe8[i].pme_activity < activity8_min ?
                        probe8[i].pme_activity : activity8_min;
        activity8_max = probe8[i].pme_activity > activity8_max ?
                        probe8[i].pme_activity : activity8_max;
        min8x = min_i(min8x, probe8[i].ime_mv_full.x);
        max8x = max_i(max8x, probe8[i].ime_mv_full.x);
        min8y = min_i(min8y, probe8[i].ime_mv_full.y);
        max8y = max_i(max8y, probe8[i].ime_mv_full.y);
        parent_diff = mv_diff_l1(probe8[i].ime_mv_full,
                                 probe16[i >> 2].ime_mv_full);
        root_diff = mv_diff_l1(probe8[i].ime_mv_full, root->ime_mv_full);
        mv8_parent_sum += parent_diff;
        mv8_root_sum += root_diff;
        mv8_parent_max = parent_diff > mv8_parent_max ? parent_diff : mv8_parent_max;
        mv8_root_max = root_diff > mv8_root_max ? root_diff : mv8_root_max;
        boundary_count +=
            abs_u32(probe8[i].ime_mv_full.x - probe8[i].ime_center_full.x) >= (uint32_t)ime_range_x ||
            abs_u32(probe8[i].ime_mv_full.y - probe8[i].ime_center_full.y) >= (uint32_t)ime_range_y;
    }

    out->value[MS_SAD16_MEAN] = (uint32_t)((sad16_sum + 2u) >> 2);
    out->value[MS_SAD8_MEAN] = (uint32_t)((sad8_sum + 8u) >> 4);
    out->value[MS_SAD16_RANGE] = sad16_max - sad16_min;
    out->value[MS_SAD8_RANGE] = sad8_max - sad8_min;
    {
        uint64_t mad16 = 0, mad8 = 0, gain_sum = 0;
        uint32_t gain_max = 0;
        for (i = 0; i < 4; ++i)
            mad16 += abs_u32((int)sad16[i] - (int)out->value[MS_SAD16_MEAN]);
        for (i = 0; i < 16; ++i)
            mad8 += abs_u32((int)sad8[i] - (int)out->value[MS_SAD8_MEAN]);
        out->value[MS_SAD16_MAD] = (uint32_t)((mad16 + 2u) >> 2);
        out->value[MS_SAD8_MAD] = (uint32_t)((mad8 + 8u) >> 4);
        out->value[MS_GAIN32_16] = out->value[MS_SAD32] > out->value[MS_SAD16_MEAN] ?
            out->value[MS_SAD32] - out->value[MS_SAD16_MEAN] : 0;
        for (i = 0; i < 4; ++i)
        {
            uint32_t child_mean = (sad8[4 * i] + sad8[4 * i + 1] +
                                   sad8[4 * i + 2] + sad8[4 * i + 3] + 2u) >> 2;
            uint32_t gain = sad16[i] > child_mean ? sad16[i] - child_mean : 0;
            gain_sum += gain;
            gain_max = gain > gain_max ? gain : gain_max;
        }
        out->value[MS_GAIN16_8] = (uint32_t)((gain_sum + 2u) >> 2);
        out->value[MS_GAIN16_8_MAX] = gain_max;
    }
    out->value[MS_MV16_ROOT_MEAN] = (uint32_t)((mv16_root_sum + 2u) >> 2);
    out->value[MS_MV16_ROOT_MAX] = mv16_root_max;
    out->value[MS_MV16_SPAN] = (uint32_t)(max16x - min16x + max16y - min16y);
    out->value[MS_MV8_PARENT_MEAN] = (uint32_t)((mv8_parent_sum + 8u) >> 4);
    out->value[MS_MV8_PARENT_MAX] = mv8_parent_max;
    out->value[MS_MV8_ROOT_MEAN] = (uint32_t)((mv8_root_sum + 8u) >> 4);
    out->value[MS_MV8_ROOT_MAX] = mv8_root_max;
    out->value[MS_MV8_SPAN] = (uint32_t)(max8x - min8x + max8y - min8y);
    out->value[MS_ACTIVITY16_MEAN] = (uint32_t)((activity16_sum + 2u) >> 2);
    out->value[MS_ACTIVITY16_RANGE] = activity16_max - activity16_min;
    out->value[MS_ACTIVITY8_MEAN] = (uint32_t)((activity8_sum + 8u) >> 4);
    out->value[MS_ACTIVITY8_RANGE] = activity8_max - activity8_min;
    out->value[MS_BOUNDARY_COUNT] = boundary_count;
    out->valid = 1;
    return 0;
}

int hw_hme_select_inter_layers_multiscale(
    const hw_hme_inter_scale_features* features, int probability_cutoff,
    hw_hme_inter_layer_decision* decision)
{
    uint32_t probability;
    if (!features || !features->valid || !decision ||
        probability_cutoff < 0 || probability_cutoff > 100)
        return -1;
    memset(decision, 0, sizeof(*decision));
    decision->features.ime_sad_per_pixel_q8 = features->value[MS_SAD32];
    decision->features.pme_to_ime_l1 = features->value[MS_REFINE32];
    decision->features.ime_mvd_qpel_l1 = features->value[MS_MVD32];
    decision->features.ime_mv_fullpel_l1 = features->value[MS_MV32];
    decision->features.pme_activity = features->value[MS_ACTIVITY32];
    decision->features.ime_boundary = (uint8_t)features->value[MS_BOUNDARY32];
    probability = hwInterMultiscaleLowProbability(features->value);
    decision->low2_probability = probability;
    decision->layer_set = probability >= (uint32_t)probability_cutoff ?
                          HW_HME_INTER_LOW_16_8 : HW_HME_INTER_HIGH_32_16;
    return 0;
}

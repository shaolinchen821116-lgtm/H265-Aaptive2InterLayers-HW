#include "intra_layer_selector.h"

#define U64(v) ((uint64_t)(v))

static uint32_t block_sad_to_mean(const uint8_t *src, ptrdiff_t stride, int log2_size)
{
    const int size = 1 << log2_size;
    const uint32_t count = 1u << (log2_size * 2);
    uint32_t sum = 0;
    uint32_t sad = 0;
    int x, y;

    for (y = 0; y < size; ++y)
        for (x = 0; x < size; ++x)
            sum += src[y * stride + x];

    {
        const int mean = (int)((sum + (count >> 1)) >> (log2_size * 2));
        for (y = 0; y < size; ++y)
            for (x = 0; x < size; ++x)
            {
                int diff = (int)src[y * stride + x] - mean;
                sad += (uint32_t)(diff < 0 ? -diff : diff);
            }
    }
    return sad;
}

static void extract_features(const uint8_t *src, ptrdiff_t stride, IntraLayerFeaturesC *f)
{
    int x, y, q, b;

    f->sad32 = block_sad_to_mean(src, stride, 5);
    f->sad16 = 0;
    f->sad8 = 0;
    for (q = 0; q < 4; ++q)
    {
        const int qx = (q & 1) << 4;
        const int qy = (q >> 1) << 4;
        const uint8_t *src16 = src + qy * stride + qx;
        f->sad16 += block_sad_to_mean(src16, stride, 4);
        for (b = 0; b < 4; ++b)
        {
            const int bx = (b & 1) << 3;
            const int by = (b >> 1) << 3;
            f->sad8 += block_sad_to_mean(src16 + by * stride + bx, stride, 3);
        }
    }

    f->grad_h = f->grad_v = f->laplacian = 0;
    f->edge4 = f->edge8 = f->edge16 = f->edge32 = 0;
    for (y = 0; y < 32; ++y)
    {
        for (x = 0; x < 32; ++x)
        {
            const int p = src[y * stride + x];
            if (x)
            {
                int d = p - src[y * stride + x - 1];
                d = d < 0 ? -d : d;
                f->grad_h += (uint32_t)d;
                f->edge4 += d >= 4;
                f->edge8 += d >= 8;
                f->edge16 += d >= 16;
                f->edge32 += d >= 32;
            }
            if (y)
            {
                int d = p - src[(y - 1) * stride + x];
                d = d < 0 ? -d : d;
                f->grad_v += (uint32_t)d;
                f->edge4 += d >= 4;
                f->edge8 += d >= 8;
                f->edge16 += d >= 16;
                f->edge32 += d >= 32;
            }
            if (x && x < 31 && y && y < 31)
            {
                int h = src[y * stride + x - 1] + src[y * stride + x + 1] - (p << 1);
                int v = src[(y - 1) * stride + x] + src[(y + 1) * stride + x] - (p << 1);
                h = h < 0 ? -h : h;
                v = v < 0 ? -v : v;
                f->laplacian += (uint32_t)(h + v);
            }
        }
    }
}

static uint32_t qp_to_qstep_q8(int qp)
{
    static const uint16_t base_q8[6] = { 256, 287, 323, 362, 406, 456 };
    int q;
    if (qp < 4) qp = 4;
    if (qp > 51) qp = 51;
    q = qp - 4;
    return (uint32_t)base_q8[q % 6] << (q / 6);
}

#include "intra_only32_tree.inc"

static uint32_t low_score(const IntraLayerFeaturesC *f)
{
    const uint64_t sad16_q8 = U64(f->sad16) << 8;
    const uint64_t sad8_q8 = U64(f->sad8) << 8;
    const uint32_t grad = f->grad_h + f->grad_v;

    if (sad16_q8 <= U64(175) * f->qstep_q8)
    {
        if (f->edge32 <= 4)
        {
            if (sad8_q8 <= U64(84) * f->qstep_q8)
                return sad8_q8 <= U64(59) * f->qstep_q8 ? 1 : 6;
            return f->edge16 <= 5 ? 5 : 29;
        }
        if (sad16_q8 <= U64(92) * f->qstep_q8)
            return sad16_q8 <= U64(68) * f->qstep_q8 ? 7 : 25;
        return f->edge4 <= 1182 ? 63 : 43;
    }

    if (f->edge32 == 0)
    {
        if ((U64(f->laplacian) << 8) <= U64(1177) * f->qstep_q8)
            return U64(grad) * 1000 <= U64(1175) * f->sad8 ? 15 : 37;
        return U64(f->laplacian) * 1000 <= U64(1098) * grad ? 24 : 70;
    }

    if (f->edge32 <= 36)
        return f->edge4 <= 1086 ? 90 : 63;

    {
        const uint32_t gain32 = f->sad32 > f->sad16 ? f->sad32 - f->sad16 : 0;
        return (U64(gain32) << 8) <= U64(108) * f->qstep_q8 ? 86 : 96;
    }
}

IntraLayerResultC intra_layer_select_y8_32x32(const uint8_t *y, ptrdiff_t y_stride, int qp)
{
    IntraLayerResultC result;
    extract_features(y, y_stride, &result.features);
    result.features.qstep_q8 = qp_to_qstep_q8(qp);
    result.low_score = low_score(&result.features);
    result.only32_score = intra_only32_score(&result.features);
    result.layer_set = result.low_score >= 40
                     ? INTRA_LAYER_C_LOW_16_8
                     : INTRA_LAYER_C_HIGH_32_16;
    return result;
}

IntraLayerResultC intra_layer_select_cascade_y8_32x32(
    const uint8_t *y, ptrdiff_t y_stride, int qp, uint32_t only32_cutoff)
{
    IntraLayerResultC result = intra_layer_select_y8_32x32(y, y_stride, qp);
    if (only32_cutoff < 1) only32_cutoff = 1;
    if (only32_cutoff > 99) only32_cutoff = 99;
    if (result.only32_score >= only32_cutoff)
        result.layer_set = INTRA_LAYER_C_ONLY_32;
    return result;
}

IntraLayerResultC intra_layer_select_cascade_i420_32x32(
    const uint8_t i420_block[1536], int qp, uint32_t only32_cutoff)
{
    return intra_layer_select_cascade_y8_32x32(i420_block, 32, qp, only32_cutoff);
}

IntraLayerResultC intra_layer_select_i420_32x32(const uint8_t i420_block[1536], int qp)
{
    return intra_layer_select_y8_32x32(i420_block, 32, qp);
}

/* Generated deterministically by export_two_layer_c.py. */
static uint32_t generated_low_score(const IntraLayerFeaturesC *f, int qp)
{
    const uint32_t gain32 = f->sad32 > f->sad16 ? f->sad32 - f->sad16 : 0;
    const uint32_t gain8 = f->sad16 > f->sad8 ? f->sad16 - f->sad8 : 0;
    const uint32_t grad = f->grad_h + f->grad_v;
    const uint32_t anisotropy = f->grad_h > f->grad_v ? f->grad_h - f->grad_v : f->grad_v - f->grad_h;
    (void)qp;
    if ((uint64_t)(f->sad16) * 256000000ULL <= 174628289ULL * (f->qstep_q8))
        if (f->edge32 <= 4.5)
            if ((uint64_t)(f->sad8) * 256000000ULL <= 83596155ULL * (f->qstep_q8))
                if ((uint64_t)(f->sad8) * 256000000ULL <= 59029557ULL * (f->qstep_q8))
                    return 0; /* n=66039, p_low=0.0046 */
                else
                    return 6; /* n=14725, p_low=0.0553 */
            else
                if (f->edge16 <= 5.5)
                    return 5; /* n=12799, p_low=0.0538 */
                else
                    return 29; /* n=7892, p_low=0.2945 */
        else
            if ((uint64_t)(f->sad16) * 256000000ULL <= 92388104ULL * (f->qstep_q8))
                if ((uint64_t)(f->sad16) * 256000000ULL <= 67769737ULL * (f->qstep_q8))
                    return 7; /* n=5842, p_low=0.0661 */
                else
                    return 25; /* n=3957, p_low=0.2474 */
            else
                if (f->edge4 <= 1182.5)
                    return 63; /* n=7355, p_low=0.6336 */
                else
                    return 43; /* n=4824, p_low=0.4268 */
    else
        if (f->edge32 <= 0.5)
            if ((uint64_t)(f->laplacian) * 256000000ULL <= 1177032020ULL * (f->qstep_q8))
                if ((uint64_t)(grad) * 1000000ULL <= 1174696ULL * (f->sad8 + 1))
                    return 15; /* n=28670, p_low=0.1540 */
                else
                    return 37; /* n=32733, p_low=0.3654 */
            else
                if ((uint64_t)(f->laplacian) * 1000000ULL <= 1097960ULL * (grad + 1))
                    return 24; /* n=6779, p_low=0.2360 */
                else
                    return 70; /* n=48427, p_low=0.6976 */
        else
            if (f->edge32 <= 36.5)
                if (f->edge4 <= 1086.5)
                    return 90; /* n=34818, p_low=0.8965 */
                else
                    return 63; /* n=21661, p_low=0.6319 */
            else
                if ((uint64_t)(gain32) * 256000000ULL <= 107686471ULL * (f->qstep_q8))
                    return 86; /* n=29242, p_low=0.8633 */
                else
                    return 96; /* n=44119, p_low=0.9632 */
}

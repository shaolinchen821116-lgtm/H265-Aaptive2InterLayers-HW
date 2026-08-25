/****************************************************************************
 * Hardware-oriented PME -> IME -> FME research search for x265.
 *
 * Coordinate contract (never mix these units implicitly):
 *   pmeMvDs       : integer samples on the 1/4-resolution original-luma plane
 *   imeMvFullPel  : integer samples on the full-resolution recon plane
 *   fmeMvQPel     : HEVC/x265 quarter-pel motion-vector units
 ****************************************************************************/

#ifndef X265_HW_HME_H
#define X265_HW_HME_H

#include "common.h"
#include "mv.h"

namespace X265_NS {

struct HardwareHMETrace
{
    MV       pmeMvDs;
    MV       imeCenterFullPel;
    MV       imeMvFullPel;
    MV       fmeMvQPel;
    uint32_t pmeSad;
    uint32_t pmeMvdBits;
    uint64_t pmeCost;
    uint16_t pmeActivity;
    uint16_t pmeRateWeightQ8;
    uint8_t  pmeTextureClass;
    uint8_t  pmeUsedAmvp;
    uint32_t imeSad;
    uint32_t imeMvdBits;
    uint32_t imeMvCost;
    uint32_t fmeSad;
    uint32_t fmeMvCost;
    uint32_t pmeCandidates;
    uint32_t imeCandidates;
    uint32_t fmeCandidates;

    HardwareHMETrace() { memset(this, 0, sizeof(*this)); }
};

/* PME is searched on a 1/4 plane. One PME sample is four full-resolution
 * integer pels and sixteen x265 qpel units. */
static inline MV hwPmeDsToImeFullPel(const MV& mv) { return mv * 4; }
static inline MV hwImeFullPelToQPel(const MV& mv)  { return mv * 4; }
static inline MV hwPmeDsToQPel(const MV& mv)       { return mv * 16; }

}

#endif

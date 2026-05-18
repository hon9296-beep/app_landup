package com.landup.common;

import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
public class BrandDefaultsService {

    private final BrandDefaultsRepository repo;

    public BrandDefaults get() {
        return repo.getSingleton();
    }

    @Transactional
    public BrandDefaults update(BrandDefaults patch) {
        // TODO Phase B: admin 권한 체크
        BrandDefaults current = repo.getSingleton();
        if (patch.getClearspaceMm() != null) current.setClearspaceMm(patch.getClearspaceMm());
        if (patch.getLogoClearspaceMm() != null) current.setLogoClearspaceMm(patch.getLogoClearspaceMm());
        if (patch.getCharacterOrientation() != null) current.setCharacterOrientation(patch.getCharacterOrientation());
        if (patch.getMainCorridorMinMm() != null) current.setMainCorridorMinMm(patch.getMainCorridorMinMm());
        if (patch.getEmergencyPathMinMm() != null) current.setEmergencyPathMinMm(patch.getEmergencyPathMinMm());
        if (patch.getWallClearanceMm() != null) current.setWallClearanceMm(patch.getWallClearanceMm());
        if (patch.getObjectGapMm() != null) current.setObjectGapMm(patch.getObjectGapMm());
        if (patch.getMainArteryHalfBufferMm() != null) current.setMainArteryHalfBufferMm(patch.getMainArteryHalfBufferMm());
        if (patch.getCorridorHalfBufferMm() != null) current.setCorridorHalfBufferMm(patch.getCorridorHalfBufferMm());
        if (patch.getInnerWallBufferMm() != null) current.setInnerWallBufferMm(patch.getInnerWallBufferMm());
        if (patch.getDefaultHeightMm() != null) current.setDefaultHeightMm(patch.getDefaultHeightMm());
        if (patch.getMaxDensityRatio() != null) current.setMaxDensityRatio(patch.getMaxDensityRatio());
        if (patch.getMaxFallbackRounds() != null) current.setMaxFallbackRounds(patch.getMaxFallbackRounds());
        return repo.save(current);
    }
}

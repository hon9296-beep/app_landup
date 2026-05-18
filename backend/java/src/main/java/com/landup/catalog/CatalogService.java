package com.landup.catalog;

import com.landup.common.ApiException;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * ObjectPalette + sub-rule(Range/Alias/MaxCount/PairRule/Clearance/WallAttachment) 묶음 조회.
 * 기존 FurnitureStandard 대체.
 */
@Service
@RequiredArgsConstructor
public class CatalogService {

    private final ObjectPaletteRepository paletteRepo;
    private final ObjectRangeRepository rangeRepo;
    private final ObjectAliasRepository aliasRepo;
    private final ObjectMaxCountRepository maxCountRepo;
    private final ObjectPairRuleRepository pairRuleRepo;
    private final ObjectClearanceRepository clearanceRepo;
    private final ObjectWallAttachmentRepository wallAttachmentRepo;

    public List<ObjectPalette> listAll() {
        return paletteRepo.findAll();
    }

    public ObjectPalette getByCode(String code) {
        return paletteRepo.findByCode(code)
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "object_palette not found: " + code));
    }

    /** 오브젝트 1종의 모든 사이드데이터 묶음 조회 (프론트 편집 UI용). */
    public Map<String, Object> getBundle(String code) {
        ObjectPalette palette = getByCode(code);
        Map<String, Object> bundle = new HashMap<>();
        bundle.put("palette", palette);
        bundle.put("ranges", rangeRepo.findAllByObjectPaletteId(palette.getId()));
        bundle.put("aliases", aliasRepo.findAllByObjectPaletteId(palette.getId()));
        bundle.put("max_count", maxCountRepo.findAllByObjectPaletteId(palette.getId()));
        bundle.put("clearance", clearanceRepo.findByObjectPaletteId(palette.getId()).orElse(null));
        bundle.put("wall_attachment", wallAttachmentRepo.findByObjectPaletteId(palette.getId()).orElse(null));
        bundle.put("pair_rules_as_a", pairRuleRepo.findAllByObjectACode(code));
        return bundle;
    }

    /** alias로 palette 역조회 (사용자가 한글명 등으로 참조할 때). */
    public ObjectPalette resolveByAlias(String alias) {
        ObjectAlias a = aliasRepo.findByAlias(alias)
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "alias not found: " + alias));
        return paletteRepo.findById(a.getObjectPaletteId())
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "palette missing for alias"));
    }

    public List<ObjectPairRule> listPairRules(ObjectPairRule.Source source) {
        return pairRuleRepo.findAllBySource(source);
    }
}

package com.landup.file;

import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import java.util.List;

/**
 * BrandManual 의 하위 오브젝트 스펙(brand_object_specs) 관리.
 * 브랜드북 분석(brand done) 시 BrandManualService가 여기로 저장 위임.
 */
@Service
@RequiredArgsConstructor
public class BrandObjectSpecService {

    private final BrandObjectSpecRepository repo;

    public List<BrandObjectSpec> listByManual(Long brandManualId) {
        return repo.findAllByBrandManualIdOrderBySeqAsc(brandManualId);
    }

    public List<BrandObjectSpec> listByType(String objectType) {
        return repo.findAllByObjectType(objectType);
    }

    public List<BrandObjectSpec> saveAll(List<BrandObjectSpec> specs) {
        // TODO Phase B: 기존 brandManualId 건 선삭제 후 일괄 INSERT 고려
        return repo.saveAll(specs);
    }
}

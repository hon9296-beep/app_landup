package com.landup.common;

import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import java.util.List;

@Service
@RequiredArgsConstructor
public class AreaTypeService {

    private final AreaTypeRepository repo;

    public List<AreaType> listActive() {
        return repo.findAllByIsActiveTrueOrderByDisplayOrderAsc();
    }

    public AreaType getByCode(String code) {
        return repo.findByCode(code)
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "area_type not found: " + code));
    }
}

package com.landup.file;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

import java.util.Map;

@Slf4j
@Service
@RequiredArgsConstructor
public class CrossSectionService {

    private final CrossSectionRepository crossSectionRepository;

    public CrossSection save(MultipartFile file, String fileType, Long userId,
                             Long floorDetectionId, Map<String, Object> pythonResult) {
        Float sectionCeilingMm = null;
        Float confidence = null;
        CrossSection.CrossSectionStatus status = CrossSection.CrossSectionStatus.error;
        String errorMessage = null;

        Object heightVal = pythonResult.get("ceiling_height_mm");
        Object confVal = pythonResult.get("confidence");

        if (heightVal != null) {
            sectionCeilingMm = ((Number) heightVal).floatValue();
            status = CrossSection.CrossSectionStatus.done;
        } else {
            errorMessage = "층고 추출 실패";
        }
        if (confVal != null) {
            confidence = ((Number) confVal).floatValue();
        }

        CrossSection cs = CrossSection.builder()
                .userId(userId)
                .floorDetectionId(floorDetectionId)
                .originalFilename(file.getOriginalFilename() != null ? file.getOriginalFilename() : "unknown")
                .storedFilename(file.getOriginalFilename() != null ? file.getOriginalFilename() : "unknown")
                .fileType(fileType)
                .status(status)
                .sectionCeilingMm(sectionCeilingMm)
                .confidence(confidence)
                .errorMessage(errorMessage)
                .build();

        crossSectionRepository.save(cs);
        log.info("[DB] cross_sections INSERT (id={}, ceiling={}mm, confidence={})",
                cs.getId(), sectionCeilingMm, confidence);
        return cs;
    }
}

package com.landup.catalog;

import org.springframework.data.jpa.repository.JpaRepository;
import java.util.Optional;

public interface ObjectWallAttachmentRepository extends JpaRepository<ObjectWallAttachment, Long> {
    Optional<ObjectWallAttachment> findByObjectPaletteId(Long objectPaletteId);
}

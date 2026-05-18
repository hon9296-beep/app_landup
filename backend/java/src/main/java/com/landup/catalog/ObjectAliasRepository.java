package com.landup.catalog;

import org.springframework.data.jpa.repository.JpaRepository;
import java.util.List;
import java.util.Optional;

public interface ObjectAliasRepository extends JpaRepository<ObjectAlias, Long> {
    Optional<ObjectAlias> findByAlias(String alias);
    List<ObjectAlias> findAllByObjectPaletteId(Long objectPaletteId);
}

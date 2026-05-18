package com.landup.catalog;

import org.springframework.data.jpa.repository.JpaRepository;
import java.util.List;
import java.util.Optional;

public interface ObjectPaletteRepository extends JpaRepository<ObjectPalette, Long> {
    Optional<ObjectPalette> findByCode(String code);
    List<ObjectPalette> findAllByFixtureRole(String fixtureRole);
    List<ObjectPalette> findAllByIsStructuralTrue();
}

package com.landup.common;

import jakarta.persistence.*;
import lombok.*;

@Entity
@Table(name = "space_cap_rules",
       uniqueConstraints = @UniqueConstraint(name = "uk_scope_key", columnNames = {"scope", "keyName"}),
       indexes = @Index(name = "idx_scope_kind", columnList = "scope,keyKind"))
@Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
public class SpaceCapRule {

    @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false, length = 32)
    private String scope;

    @Column(nullable = false, length = 64)
    private String keyName;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 20)
    private KeyKind keyKind;

    @Column(nullable = false)
    private Short capValue;

    @Column(columnDefinition = "TEXT")
    private String reasonNote;

    public enum KeyKind { object_type, fixture_role }
}

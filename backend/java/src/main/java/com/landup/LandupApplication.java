package com.landup;

import com.fasterxml.jackson.databind.PropertyNamingStrategy;
import com.fasterxml.jackson.databind.cfg.MapperConfig;
import com.fasterxml.jackson.databind.introspect.AnnotatedField;
import com.fasterxml.jackson.databind.introspect.AnnotatedMethod;
import org.hibernate.boot.model.naming.Identifier;
import org.hibernate.boot.model.naming.PhysicalNamingStrategy;
import org.hibernate.boot.model.naming.PhysicalNamingStrategyStandardImpl;
import org.hibernate.engine.jdbc.env.spi.JdbcEnvironment;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.autoconfigure.orm.jpa.HibernatePropertiesCustomizer;
import org.springframework.context.annotation.Bean;
import org.springframework.scheduling.annotation.EnableScheduling;

@SpringBootApplication
@EnableScheduling
public class LandupApplication {
    public static void main(String[] args) {
        SpringApplication.run(LandupApplication.class, args);
    }

    @Bean
    public PhysicalNamingStrategy physicalNamingStrategy() {
        return new AggressiveSnakeCaseStrategy();
    }

    @Bean
    public HibernatePropertiesCustomizer hibernateNamingCustomizer() {
        return properties -> properties.put(
            "hibernate.physical_naming_strategy",
            "com.landup.LandupApplication$AggressiveSnakeCaseStrategy"
        );
    }

    /**
     * Jackson JSON 응답 필드명 변환 도구 — Hibernate AggressiveSnakeCaseStrategy 와 동일 규칙.
     *
     * 사용처: snake_case 응답이 필요한 DTO 클래스에 명시적 opt-in.
     *   @JsonNaming(LandupApplication.AggressiveSnakeCaseJacksonStrategy.class)
     *   public class SomeDto { ... }
     *
     * Spring Boot 기본 SNAKE_CASE (LowerSnakeCaseStrategy) 는 `centerXMm` 같은 연속 대문자를
     * acronym 으로 보고 `center_xmm` 로 잘못 변환. 본 전략은 모든 대문자 앞 `_` 삽입 →
     * `centerXMm` → `center_x_mm`.
     *
     * 주의: 글로벌 @Bean 으로 박지 말 것 — camel 기대 DTO 까지 변환되어 프론트 회귀 발생함
     *      (2026-05-10 글로벌 적용 → 2026-05-15 폐기, per-class opt-in 으로 전환).
     */
    public static class AggressiveSnakeCaseJacksonStrategy extends PropertyNamingStrategy {
        @Override
        public String nameForField(MapperConfig<?> config, AnnotatedField field, String defaultName) {
            return convert(defaultName);
        }
        @Override
        public String nameForGetterMethod(MapperConfig<?> config, AnnotatedMethod method, String defaultName) {
            return convert(defaultName);
        }
        @Override
        public String nameForSetterMethod(MapperConfig<?> config, AnnotatedMethod method, String defaultName) {
            return convert(defaultName);
        }
        @Override
        public String nameForConstructorParameter(MapperConfig<?> config,
                                                  com.fasterxml.jackson.databind.introspect.AnnotatedParameter param,
                                                  String defaultName) {
            return convert(defaultName);
        }
        private static String convert(String name) {
            if (name == null || name.isEmpty()) return name;
            String snake = name.replaceAll("([A-Z])", "_$1").toLowerCase();
            if (snake.startsWith("_")) snake = snake.substring(1);
            return snake;
        }
    }

    /**
     * camelCase → snake_case 변환. 모든 대문자 앞에 `_` 삽입.
     *   centerXMm → center_x_mm  ✓
     *   pdfSha256 → pdf_sha256    ✓
     *   userId    → user_id       ✓
     *
     * Hibernate 기본 CamelCaseToUnderscoresNamingStrategy 는 `XMm` 같은 연속 대문자를
     * acronym 으로 보고 `_` 삽입 안 함. 이 커스텀은 그 케이스도 처리.
     * PhysicalNamingStrategyStandardImpl 을 직접 상속해서 public API 만 사용 (Hibernate 6 호환).
     */
    public static class AggressiveSnakeCaseStrategy extends PhysicalNamingStrategyStandardImpl {
        @Override
        public Identifier toPhysicalColumnName(Identifier name, JdbcEnvironment context) {
            return convert(name);
        }

        @Override
        public Identifier toPhysicalTableName(Identifier name, JdbcEnvironment context) {
            return convert(name);
        }

        private Identifier convert(Identifier name) {
            if (name == null) return null;
            String text = name.getText();
            String snake = text.replaceAll("([A-Z])", "_$1").toLowerCase();
            if (snake.startsWith("_")) snake = snake.substring(1);
            return Identifier.toIdentifier(snake, name.isQuoted());
        }
    }
}

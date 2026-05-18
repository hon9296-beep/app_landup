package com.landup.common;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.converter.json.Jackson2ObjectMapperBuilder;

@Configuration
public class JacksonConfig {

    /**
     * Spring Boot의 Jackson2ObjectMapperBuilder를 통해 ObjectMapper를 생성.
     * 자동 등록되는 모듈(JavaTimeModule 포함) + spring.jackson.* 설정 모두 적용.
     *
     * 직접 new ObjectMapper() 하면 LocalDateTime 등 java.time 타입 직렬화 실패함.
     */
    @Bean
    public ObjectMapper objectMapper(Jackson2ObjectMapperBuilder builder) {
        return builder.build();
    }
}
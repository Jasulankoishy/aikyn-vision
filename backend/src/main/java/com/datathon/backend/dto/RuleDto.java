package com.datathon.backend.dto;

import com.fasterxml.jackson.annotation.JsonAlias;
import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@JsonIgnoreProperties(ignoreUnknown = true)
public class RuleDto {
    private String id;
    private String document;
    private String section;

    // Every other field in the API is snake_case; this one was camelCase.
    // CONFIRM against the datathon API spec / what analyze.py emits.
    @JsonProperty("source_url")
    @JsonAlias("sourceUrl")
    private String sourceUrl;
}
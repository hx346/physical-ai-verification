package com.roboverify.platform.project;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.roboverify.platform.project.dto.CreateProjectRequest;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * standalone MockMvc：不拉 Spring 上下文，不需要数据库（CI 无 DB 也能跑）。
 */
@ExtendWith(MockitoExtension.class)
class ProjectControllerTest {

    @Mock
    private ProjectService projectService;

    private MockMvc mockMvc;
    private final ObjectMapper objectMapper = new ObjectMapper();

    @BeforeEach
    void setUp() {
        mockMvc = MockMvcBuilders.standaloneSetup(new ProjectController(projectService, () -> "admin")).build();
    }

    @Test
    void createProjectReturnsOkWithId() throws Exception {
        ProjectRow project = new ProjectRow("p-001", "发动机零件自动抓取", "demo", "ACTIVE",
                "admin", null, null);
        when(projectService.create(any(CreateProjectRequest.class), eq("admin"))).thenReturn(project);

        mockMvc.perform(post("/api/projects")
                        .header("Authorization", "mock-token")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(
                                new CreateProjectRequest("发动机零件自动抓取", "demo"))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.id").value("p-001"));
    }

    @Test
    void blankNameRejectedByValidation() throws Exception {
        mockMvc.perform(post("/api/projects")
                        .header("Authorization", "mock-token")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(new CreateProjectRequest("", null))))
                .andExpect(status().isBadRequest());
    }
}

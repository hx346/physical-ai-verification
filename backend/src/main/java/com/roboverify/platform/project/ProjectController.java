package com.roboverify.platform.project;

import com.roboverify.platform.auth.OperatorProvider;
import com.roboverify.platform.common.api.Result;
import com.roboverify.platform.project.dto.CreateProjectRequest;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/projects")
public class ProjectController {

    private final ProjectService projectService;
    private final OperatorProvider operatorProvider;

    public ProjectController(ProjectService projectService, OperatorProvider operatorProvider) {
        this.projectService = projectService;
        this.operatorProvider = operatorProvider;
    }

    @PostMapping
    public Result<ProjectRow> create(@Valid @RequestBody CreateProjectRequest request) {
        return Result.ok(projectService.create(request, operatorProvider.current()));
    }

    @GetMapping
    public Result<List<ProjectRow>> list() {
        return Result.ok(projectService.list());
    }

    @GetMapping("/{id}")
    public Result<ProjectRow> get(@PathVariable String id) {
        return Result.ok(projectService.get(id));
    }
}

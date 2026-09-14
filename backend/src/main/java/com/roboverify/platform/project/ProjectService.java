package com.roboverify.platform.project;

import com.roboverify.platform.audit.AuditService;
import com.roboverify.platform.project.dto.CreateProjectRequest;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
public class ProjectService {

    private static final String AUDIT_TARGET_TYPE = "project";

    private final ProjectRepository projectRepository;
    private final AuditService auditService;

    public ProjectService(ProjectRepository projectRepository, AuditService auditService) {
        this.projectRepository = projectRepository;
        this.auditService = auditService;
    }

    public ProjectRow create(CreateProjectRequest request, String operator) {
        ProjectRow project = projectRepository.insert(request.name(), request.description(), operator);
        auditService.record(operator, "create", AUDIT_TARGET_TYPE, project.id(), null,
                "{\"name\":\"" + request.name() + "\"}");
        return project;
    }

    public ProjectRow get(String id) {
        return projectRepository.findById(id);
    }

    public List<ProjectRow> list() {
        return projectRepository.findAll();
    }
}

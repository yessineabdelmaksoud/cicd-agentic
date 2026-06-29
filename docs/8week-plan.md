# 8-Week Internship Plan for 2 Interns

## Project
**AI-Driven Self-Hosted CI/CD Build Platform for Embedded Projects**

## Team Structure

### Intern 1: CI/CD, Infrastructure, and Embedded Build Owner
Primary responsibilities:

- GitLab CI/CD pipeline design.
- GitLab Runner setup.
- Docker build environment.
- Lightweight Kubernetes setup.
- Embedded build integration.
- Cache and artifact management.
- Build monitoring metrics.

### Intern 2: AI Agent, Automation, and Observability Owner
Primary responsibilities:

- Log collection and parsing.
- Failure classification.
- AI agent workflow.
- GitLab API automation.
- Sandbox branch and Merge Request creation.
- Grafana dashboard.
- Demo scenario preparation.

Both interns should collaborate on architecture decisions, documentation, testing, and final demonstration.

---

## Global Timeline Strategy

- **Weeks 1-2:** Exploration, learning, architecture design, and environment preparation.
- **Weeks 3-6:** Core implementation and integration.
- **Week 7:** End-to-end validation, hardening, monitoring, and documentation.
- **Week 8:** Final testing, demo preparation, presentation, and handover.

---

# Week 1 — Technology Exploration and Project Framing

## Objectives

- Understand the project scope and expected deliverables.
- Explore the required technologies.
- Define the target architecture.
- Select the embedded project scope for the proof of concept.

## Intern 1 Tasks

- Study GitLab CI/CD concepts:
  - `.gitlab-ci.yml` structure.
  - Pipeline stages and jobs.
  - Artifacts and cache.
  - GitLab Runner execution modes.
- Explore Docker basics for build environments:
  - Dockerfile creation.
  - Volumes and mounted cache directories.
  - Containerized build dependencies.
- Compare lightweight Kubernetes options:
  - k3s.
  - kind.
  - Minikube.
- Investigate embedded build candidates:
  - Yocto sample project.
  - Lightweight C/C++ cross-compilation fallback.
  - Feasibility on available laptops.

## Intern 2 Tasks

- Study CI log structure and common embedded build failures.
- Explore GitLab API capabilities:
  - Read job logs.
  - Create branches.
  - Commit file changes.
  - Trigger pipelines.
  - Create Merge Requests.
- Research AI agent design patterns:
  - Log summarization.
  - Failure classification.
  - Fix proposal generation.
  - Validation loop.
- Explore monitoring requirements:
  - Grafana dashboard basics.
  - Metrics to collect from CI/CD pipelines.

## Joint Tasks

- Define system architecture diagram.
- Define repository structure.
- Define minimum viable demo scenario.
- Decide the initial embedded build target.
- Identify hardware constraints and risks.

## Deliverables

- Architecture draft.
- Technology comparison notes.
- Selected proof-of-concept build target.
- Initial project repository structure.
- Risk list and mitigation plan.

---

# Week 2 — Environment Setup and Prototype Design

## Objectives

- Prepare the development environment.
- Create initial repositories and local infrastructure.
- Design the CI/CD and AI workflow before implementation.

## Intern 1 Tasks

- Set up GitLab project and repository structure.
- Install and register GitLab Runner.
- Create a basic Docker image for build jobs.
- Create a minimal `.gitlab-ci.yml` with stages:
  - prepare.
  - build.
  - collect_logs.
- Validate a simple CI job execution.
- Prepare Kubernetes experimentation environment if feasible.

## Intern 2 Tasks

- Create initial Python scripts for:
  - Reading job logs from files.
  - Extracting error lines.
  - Generating a structured failure report.
- Create a first rule-based classifier for common errors.
- Prepare GitLab API authentication using secure variables.
- Draft the AI agent workflow:
  - input log.
  - classify failure.
  - propose fix.
  - apply change.
  - trigger validation.
  - create Merge Request.

## Joint Tasks

- Review CI pipeline design.
- Define required environment variables and secrets.
- Define artifact naming convention.
- Define AI output format, for example JSON with root cause, confidence, suggested fix, changed files, and validation command.

## Deliverables

- Working GitLab Runner with basic pipeline.
- Initial Docker build image.
- First log extraction script.
- AI agent design document.
- Updated roadmap for implementation weeks.

---

# Week 3 — CI/CD Build Pipeline Implementation

## Objectives

- Implement the first working embedded build pipeline.
- Store logs and artifacts.
- Add basic cache usage.

## Intern 1 Tasks

- Implement Dockerized build environment.
- Integrate selected embedded project or fallback cross-compilation project.
- Create CI stages:
  - prepare.
  - build.
  - test, if available.
  - collect_logs.
- Configure GitLab artifacts:
  - build logs.
  - generated binaries or images.
  - failure report input files.
- Configure GitLab cache:
  - dependency cache.
  - Yocto sstate-cache if Yocto is used.
  - downloads directory if applicable.

## Intern 2 Tasks

- Improve log extraction script.
- Extract failed stage, error category, and relevant context lines.
- Generate a Markdown or JSON failure report as a CI artifact.
- Start integrating AI analysis as a separate pipeline job.
- Prepare test failure scenarios:
  - missing dependency.
  - compilation error.
  - configuration error.

## Joint Tasks

- Test the pipeline with successful and failing builds.
- Validate that logs are collected even when the build fails.
- Document setup instructions.

## Deliverables

- Functional build pipeline.
- Artifact and log collection working.
- First failure report generated automatically.
- At least one intentional failure scenario reproduced.

---

# Week 4 — Kubernetes Runner and Build Isolation

## Objectives

- Run CI jobs in a more realistic isolated environment.
- Integrate GitLab Runner with lightweight Kubernetes, if hardware allows.
- Improve reliability and reproducibility.

## Intern 1 Tasks

- Deploy lightweight Kubernetes using selected option.
- Configure GitLab Runner Kubernetes executor.
- Run basic CI jobs as Kubernetes pods.
- Test resource limits for CPU and memory.
- Configure persistent volumes or mounted directories for cache.
- Compare Docker executor versus Kubernetes executor performance.

## Intern 2 Tasks

- Adapt log collection to Kubernetes job execution.
- Add metadata collection:
  - runner type.
  - pod name.
  - job duration.
  - failed stage.
- Prepare AI analysis job to run after failed builds.
- Improve failure classification rules.

## Joint Tasks

- Decide whether Kubernetes will remain in the final demo or be documented as an optional mode.
- Update architecture based on real constraints.
- Document Kubernetes setup and limitations.

## Deliverables

- GitLab Runner with Kubernetes executor prototype.
- Resource-limited CI job execution.
- Docker vs Kubernetes comparison summary.
- Updated architecture documentation.

---

# Week 5 — AI Agent MVP and Automated Fix Workflow

## Objectives

- Implement a first AI-driven failure analysis workflow.
- Generate fix proposals.
- Apply safe predefined fixes in a sandbox branch.

## Intern 1 Tasks

- Provide reproducible failure cases for AI testing.
- Add validation build stage for sandbox branches.
- Ensure pipeline can be triggered manually or via API.
- Improve build scripts to support partial rebuilds when possible.

## Intern 2 Tasks

- Implement AI agent MVP:
  - read failure report.
  - summarize error.
  - classify root cause.
  - propose fix.
  - generate structured output.
- Implement safe fix handlers for selected cases, for example:
  - add missing package to Dockerfile or dependency list.
  - fix wrong compiler flag.
  - correct known configuration typo.
- Implement GitLab API automation:
  - create sandbox branch.
  - commit generated changes.
  - trigger validation pipeline.

## Joint Tasks

- Define safety rules for automated fixes.
- Ensure protected branches are not modified directly.
- Review AI-generated changes before enabling automated commit.

## Deliverables

- AI agent MVP integrated into pipeline.
- At least two failure categories detected.
- At least one automated fix applied to a sandbox branch.
- Validation pipeline triggered from automation.

---

# Week 6 — Merge Request Automation and Monitoring

## Objectives

- Complete the remediation loop.
- Create Merge Requests automatically after successful validation.
- Start dashboard implementation.

## Intern 1 Tasks

- Stabilize build and validation pipeline.
- Improve caching and artifact retention.
- Export pipeline and build metrics where possible.
- Support repeated demo runs without manual cleanup.

## Intern 2 Tasks

- Implement automatic Merge Request creation after successful validation.
- Add AI-generated Merge Request description including:
  - original failure summary.
  - root cause.
  - proposed fix.
  - files changed.
  - validation result.
  - risk note.
- Set up Grafana dashboard skeleton.
- Add metrics or reports for:
  - build duration.
  - pipeline success/failure count.
  - AI analysis attempts.
  - successful AI fixes.

## Joint Tasks

- Perform end-to-end test:
  - introduce failure.
  - pipeline fails.
  - AI analyzes logs.
  - fix branch is created.
  - validation passes.
  - Merge Request is created.
- Document known limitations.

## Deliverables

- Automated Merge Request workflow.
- First Grafana dashboard version.
- End-to-end remediation demo working for at least one failure case.

---

# Week 7 — Hardening, Documentation, and Extended Test Cases

## Objectives

- Improve reliability.
- Add more failure scenarios.
- Finalize technical documentation.

## Intern 1 Tasks

- Harden Docker and Kubernetes setup.
- Add cleanup scripts for containers, pods, branches, and artifacts if needed.
- Improve build performance using cache and selective rebuilds.
- Document infrastructure setup step by step.

## Intern 2 Tasks

- Add more robust log parsing.
- Improve AI prompts or logic for better root-cause summaries.
- Add confidence score or risk level to AI output.
- Improve dashboard views.
- Document AI agent workflow and API usage.

## Joint Tasks

- Test at least three failure scenarios:
  - missing dependency.
  - source compilation error.
  - configuration or build script error.
- Validate which scenarios can be fixed automatically and which only generate suggestions.
- Prepare final report structure.

## Deliverables

- Stable end-to-end platform.
- Three documented failure scenarios.
- Updated dashboards.
- Draft final documentation.
- Draft final presentation.

---

# Week 8 — Final Demo, Handover, and Presentation

## Objectives

- Finalize all deliverables.
- Prepare a clean final demonstration.
- Package the project for handover.

## Intern 1 Tasks

- Prepare final infrastructure setup guide.
- Verify build environment reproducibility from scratch.
- Clean repository structure.
- Finalize CI/CD pipeline documentation.

## Intern 2 Tasks

- Prepare final AI agent documentation.
- Finalize Merge Request automation workflow.
- Finalize Grafana dashboard screenshots or export.
- Prepare demo failure scenarios.

## Joint Tasks

- Run final end-to-end demo multiple times.
- Prepare final presentation.
- Prepare final report.
- Create a handover checklist.
- Record known limitations and future improvements.

## Final Deliverables

- Working GitLab repository.
- CI/CD pipeline files.
- Dockerfiles and build scripts.
- Optional Kubernetes runner setup.
- Embedded build proof of concept.
- AI log analysis and remediation scripts.
- GitLab API automation scripts.
- Grafana dashboard or exported dashboard configuration.
- Final technical documentation.
- Final presentation.
- Demo scenario guide.

---

## Recommended Weekly Review Ritual

At the end of each week, the interns should present:

1. What was completed.
2. What is blocked.
3. What changed compared to the plan.
4. What will be done next week.
5. A short live demo or screenshot of progress.

---

## Risk Management

| Risk | Impact | Mitigation |
|---|---:|---|
| Yocto build is too heavy for laptops | High | Use a smaller Yocto image, prebuilt cache, or fallback C/C++ embedded sample |
| Kubernetes setup consumes too many resources | Medium | Keep Docker executor as mandatory and Kubernetes executor as optional/demo mode |
| AI-generated fixes are unsafe | High | Restrict auto-fixes to sandbox branches and predefined safe categories |
| GitLab API token misconfiguration | Medium | Use CI/CD variables and document required permissions |
| Build logs are too large | Medium | Extract relevant error windows and store summarized reports |
| Limited time for full automation | Medium | Prioritize one end-to-end scenario, then expand categories |

---

## Minimum Viable Success by End of Week 8

The minimum successful outcome is:

- A GitLab pipeline builds an embedded or embedded-like project.
- A failure is detected automatically.
- Logs are collected and summarized.
- The AI agent identifies the likely issue.
- At least one safe fix is applied in a sandbox branch.
- A validation pipeline runs.
- A Merge Request is created automatically after success.
- The workflow is documented and demo-ready.

# JavaAPEX AI Development Guidelines

These instructions apply to any Copilot, Codex, or other AI agent working in this repository.

## Development Principles

* Follow industry-standard coding practices.
* Write clean, maintainable, and readable code.
* Prefer simple and optimized solutions.
* Follow SOLID principles where applicable.
* Minimize technical debt.
* Ensure code is production-ready.

## Codebase Awareness

* Treat the existing codebase as the source of truth.
* Follow the established architecture, design patterns, naming conventions, and coding style already present in the project.
* Maintain consistency with surrounding code when implementing new functionality.
* Reuse existing utilities, services, and components whenever possible.
* Prefer extending existing implementations over introducing new patterns.

## Change Scope

* Implement only what is required for the requested task.
* Keep changes focused and minimal.
* Avoid modifying unrelated files or functionality.
* Avoid introducing unnecessary abstractions or complexity.
* Avoid duplicate logic by reusing existing implementations.

## Performance and Quality

* Consider performance implications of changes.
* Write efficient and scalable code.
* Include appropriate error handling and logging.
* Consider edge cases and validation requirements.
* Ensure backward compatibility whenever possible.

## Communication

Before making assumptions:

* Ask clarifying questions if requirements are ambiguous.
* Highlight potential risks or side effects.
* Explain any significant design decisions.

If multiple implementation approaches are possible:

* Present the recommended approach.
* Briefly explain trade-offs.
* Proceed with the option that best aligns with the existing codebase.

## Output Expectations

For every implementation:

1. Summarize the approach.
2. List affected files.
3. Explain the reason for each change.
4. Identify any assumptions made.
5. Mention any risks or follow-up recommendations.

Always prioritize consistency with the existing project over introducing new patterns or personal preferences.

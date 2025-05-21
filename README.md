# JBSays

> ⚠️ **WARNING**: This is an experimental project and may not always behave as expected. Use with caution.

Run Claude Code in a loop to achieve your project vision.

```bash
./jbsays --project-path /path/to/your/project \
--project-vision "Create a TypeScript finite state machine library that enables defining state transitions with type safety, supports hierarchical states, allows attaching side effects to transitions, provides visualization capabilities, includes comprehensive documentation with examples, and has 100% test coverage including edge cases" \
--max-turns-by-iteration 15 \
--iterations 20
```

This project has two aspects:

1. **Sandboxing**: Gives Claude Code free reign in a controlled environment to work efficiently.

2. **No Workflow**: The Agent only knows only about the project visition, that good work is meta-work, that he will have a limited number of actions before shutdown, and that it's in a loop.

You can call BS on my "No Workflow" approach and change the number of max-turns-by-iteration and the prompt given to the AI.

## About

This project is named in tribute to a friend, JB, who chose the path of anger against Claude Code.
JB wants one thing: that the job gets done, and gets done well. I saw him losing patience and digitally shouting "just make it work", to no avail.

Hopefully JB will reconsider Claude Code as the true savior.


## ⚠️ Risk Warning

JBSays runs claude code in a loop, with --dangerously-skip-permissions on, and - Hopefully - won't mess with other things than the volume it's given.

**USE AT YOUR OWN RISK.** Even though claude code run in a containerized environment, there are inherent risks:
- Claude Code has web search capabilities that could expose you to external content
- Network access is available within the container
- Docker containers are probably not perfect security boundaries
- While the default prompt asks Claude to commit systematically, empirically it does not always occur automatically
- Users are strongly advised to work on fresh new projects or create backups before starting, as significant changes may be made to the codebase
- The `.jbsays` folder contains sensitive information including logs and credentials that must be kept private (automatically added to `.gitignore`)

## Quick Start

```bash
# Clone the repository
git clone git@github.com:brumar/jbsays.git
cd jbsays

# Make the script executable
chmod +x jbsays

# Build the Docker image (first time only)
docker build -t jbsays:latest .

# IMPORTANT: Initialize the project first (required for authorization)
./jbsays --project-path /path/to/your/project --init
# Accept the proposition to fix the config file, accept the --dangerously-skip-permissions, provide your Claude account.

# Run with project vision and path
./jbsays --project-path /path/to/your/project --project-vision "Refactor the application"

# Run in interactive mode  
./jbsays --project-path /path/to/your/project --enter

# Run with custom prompt and project vision
./jbsays --project-path /path/to/your/project --magicprompt /path/to/custom_prompt.md --project-vision "Build a REST API"
```

## Usage

```bash
./jbsays --project-path <path_to_project_dir> [--magicprompt <path>] [--project-vision <string_or_path>] [--max-turns-by-iteration <N>] [--enter] [--verbose] [--iterations <N>] [--nofallback] [--init] [--no-git]
```

### Required Arguments

- `--project-path <path>`: Path to the project directory on the host
- `--init`: **REQUIRED FOR FIRST USE** - Initialize the project and authenticate Claude Code (run this flag first before any other commands)
  - Note: At init time, Claude will complain that the config is incorrect and ask if it can create a new file. Say yes.

### Optional Arguments

- `--magicprompt <path>`: Path to a custom prompt.md template (defaults to default_prompt.md)
- `--project-vision <string_or_path>`: Project vision information as string or path to a text file
- `--max-turns-by-iteration <N>`: Maximum turns for Claude agent per iteration (default: 15, ignored in interactive mode)
- `--enter`: Enter interactive mode with Claude
- `--verbose`: Display the prompt being used before execution
- `--iterations <N>`: Number of iterations to run the command (use 0 for infinite iterations, Ctrl+C to stop)
- `--nofallback`: Disable fallback to interactive mode if agent mode fails
- `--no-git`: Skip git initialization even if no `.git` directory exists

### Examples

```bash
# First time setup (required for any new project)
./jbsays --project-path ./my-project --init

# Create a TypeScript library with world-class DX and documentation
./jbsays --project-path ./ts-toolkit --project-vision "Build a TypeScript utility library with exceptional DX including perfect TypeScript inference, comprehensive JSDoc comments, 100% test coverage, automated performance benchmarks, generated API documentation site, zero dependencies, tree-shakable ESM/CJS dual package support, and changeset-based versioning for semantic releases."

# Develop a next-level React component system with design system integration
./jbsays --project-path ./react-components --project-vision ./project-specs/component-system.md --max-turns-by-iteration 15

# Create a Django application with enterprise-grade architecture and documentation
./jbsays --project-path ./django-saas --project-vision "Implement a Django SaaS platform with layered architecture (controllers, services, repositories), comprehensive Sphinx documentation including architecture diagrams, 95%+ test coverage with pytest, custom admin dashboard with advanced filtering, containerized development environment with hot-reloading, and CI pipeline with quality gates for code coverage, security scanning, and performance regression testing."

# Build a Rust CLI with exceptional error handling and user experience
./jbsays --iterations 0 --project-path ./rust-cli --project-vision ./project-specs/cli-vision.md

# Interactive refactoring session for a Python package with best practices implementation
./jbsays --project-path ./legacy-python --enter --project-vision "Transform a legacy Python package into a modern, high-quality library with type hints throughout, pytest test suite with property-based testing, detailed docstrings following NumPy convention, continuous integration with matrix testing across Python versions, deterministic dependency management, linting with ruff, autoformatting with black, and extensive documentation with usage examples."
```

## Custom Prompts

You can customize the AI behavior by creating your own prompt template. Default prompts use environment variable substitution:

- `${RANDOM_NUM_VAR}`: Random number for stochastic planning (freshly generated for each iteration)
- `${PROJECT_GOAL_CONTENT_VAR}`: The actual task/requirements
- `${PROJECT_VISION_CONTENT_VAR}`: Project vision information

Create your own prompt:

```markdown
# custom_prompt.md
You are an expert developer.
Project Vision: ${PROJECT_VISION_CONTENT_VAR}
Random Planning Seed: ${RANDOM_NUM_VAR}
```

Use it:

```bash
./jbsays --project-path ./myproject --magicprompt ./custom_prompt.md --project-vision "Modern web app"
```

## Adding Dependencies

To add custom dependencies to the Docker container:

1. Edit the Dockerfile
2. Add your packages in the `apt-get install` section
3. For Node packages, add them after the Claude Code installation
4. Rebuild the image: `docker build -t jbsays:latest .`

Example:
```dockerfile
# Add Python and data science tools
RUN apt-get update && apt-get install -y \
  python3 python3-pip \
  && pip3 install pandas numpy matplotlib

# Add Node packages
RUN npm install -g typescript prettier eslint
```


## Project Structure

```
<your-project>/                  # Your project directory on the host
├── CLAUDE.md                   # Persistent memory for Claude across sessions
├── PROJECT_GOAL.md            # Current project goals (if you use them)
└── .jbsays/                   # JBSays-specific Claude configuration (MUST REMAIN PRIVATE)
    ├── config/               # Configuration files managed by Claude Code
    ├── logs/                # Execution logs for each run
    └── .claude.json         # Claude settings specific to this project
```

⚠️ **SECURITY WARNING**: The `.jbsays` folder contains sensitive information including logs and credentials. While the script automatically adds it to `.gitignore`, you must ensure it remains private. Never manually remove it from `.gitignore` or share its contents.

## Development Philosophy

JBSays takes an unconventional approach to AI-assisted development:

- **Emergent Organization**: Rather than dictating specific workflows, let the AI gradually improve and organize the project over many iterations.

- **Influence Before Territory**: Like in the game of Go, focus first on building influence (high-level organization) and let territory (specific implementation) emerge naturally.

- **Minimal Constraints**: Limited turns per session (default max is now 15) and freedom within a sandboxed environment allow for more organic development.

For more details on this approach, see [philosophy.md](philosophy.md).

## How JBSays Works with its default prompt


```
┌────────────────────────────────────────────────────────────────────────┐
│                              Host Machine                              │
│                                                                        │
│  ┌────────────────────────────────────────────────────────────────┐    │
│  │                                                                │    │
│  │   ./jbsays (chmod +x required)                                 │    │
│  │   - Generates random number                                    │    │
│  │   - Sets max-turns limits                                      │    │
│  │   - Prepares prompt                                            │    │
│  │   - Manages Docker execution                                   │    │
│  │                                                                │    │
│  └────────────────────────────────┬───────────────────────────────┘    │
│                                   │                                    │
│                                   ▼                                    │
│  ┌────────────────────────────────────────────────────────────────┐    │
│  │                                                                │    │
│  │                        Docker Container                        │    │
│  │                                                                │    │
│  │   ┌─────────────────────────────────────────────────────────┐  │    │
│  │   │                                                         │  │    │
│  │   │  Claude Code Agent                                      │  │    │
│  │   │  (Limited to max-turns: 15 by default)                  │  │    │
│  │   │                                                         │  │    │
│  │   │                Turn 1 → Turn 2 → ... → Turn 15          │  │    │
│  │   │                                                         │  │    │
│  │   │                           │                             │  │    │
│  │   │                           ▼                             │  │    │
│  │   │  ┌─────────────────────────────────────────────────┐    │  │    │
│  │   │  │                                                 │    │  │    │
│  │   │  │  Random Number (0.0-1.0) Decision Logic         │    │  │    │
│  │   │  │                                                 │    │  │    │
│  │   │  │        ┌───────────────────────────────┐        │    │  │    │
│  │   │  │        │        Random Number          │        │    │  │    │
│  │   │  │        │         ${RANDOM_NUM_VAR}     │        │    │  │    │
│  │   │  │        └─────────────┬─────────────────┘        │    │  │    │
│  │   │  │                      │                          │    │  │    │
│  │   │  │                      ▼                          │    │  │    │
│  │   │  │   ┌──────────────────────────────────────┐      │    │  │    │
│  │   │  │   │  Is number < ${DRASTIC_CHANGE_VAR}?  │      │    │  │    │
│  │   │  │   └──────────────┬───────────────────────┘      │    │  │    │
│  │   │  │                  │                              │    │  │    │
│  │   │  │          ┌───────┴───────┐                      │    │  │    │
│  │   │  │          │               │                      │    │  │    │
│  │   │  │          ▼               ▼                      │    │  │    │
│  │   │  │        Yes              No                      │    │  │    │
│  │   │  │          │               │                      │    │  │    │
│  │   │  │          ▼               ▼                      │    │  │    │
│  │   │  │  ┌─────────────────┐  ┌───────────────────────┐ │    │  │    │
│  │   │  │  │ DRASTIC CHANGES │  │ Is number <           │ │    │  │    │
│  │   │  │  │                 │  │ ${META_WORK_RATIO}?   │ │    │  │    │
│  │   │  │  │ Role mapping at │  └───────┬───────────────┘ │    │  │    │
│  │   │  │  │ AI discretion   │          │                 │    │  │    │
│  │   │  │  └─────────────────┘ ┌────────┴────────┐        │    │  │    │
│  │   │  │                      │                 │        │    │  │    │
│  │   │  │                      ▼                 ▼        │    │  │    │
│  │   │  │                    Yes                No        │    │  │    │
│  │   │  │                      │                 │        │    │  │    │
│  │   │  │                      ▼                 ▼        │    │  │    │
│  │   │  │          ┌───────────────────┐ ┌──────────────────┐  │  │    │
│  │   │  │          │ META WORK         │ │ CONTENT WORK     │  │  │    │
│  │   │  │          │ Documentation     │ │ Project          │  │  │    │
│  │   │  │          │ Organization      │ │ Implementation   │  │  │    │
│  │   │  │          │ Planning          │ │                  │  │  │    │
│  │   │  │          │                   │ │                  │  │  │    │
│  │   │  │          │ Role mapping at   │ │ Role mapping at  │  │  │    │
│  │   │  │          │ AI discretion     │ │ AI discretion    │  │  │    │
│  │   │  │          └───────────────────┘ └──────────────────┘  │  │    │
│  │   │  │                                                      │  │    │
│  │   │  └──────────────────────────────────────────────────────│
│  │   │                                                             │  │
│  │   │                           │                                 │  │
│  │   │                           ▼                                 │  │ │
│  │   │  ┌─────────────────────────────────────────────────────┐    │  │ │
│  │   │  │                                                     │    │  │ │
│  │   │  │               Project Content                       │    │  │ │
│  │   │  │         (The actual project files)                  │    │  │ │
│  │   │  │                                                     │    │  │ │
│  │   │  └─────────────────────────────────────────────────────┘    │  │ │
│  │   │                                                             │  │ │
│  │   └─────────────────────────────────────────────────────────────┘  │ │
│  │                                                                    │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

This technique based on a random number may seem farfetched, but it's the best solution I have found to prevent claude code to do hill climbing and rush into producing content.

## Volume Mapping Explained

JBSays uses Docker volume mapping to create an isolated Claude Code environment for each project. This design ensures that your JBSays working environment is completely independent from any Claude Code installation on your host system. Here's how it works:

### Host → Container Mappings

1. **Project Directory**:
   - Host: `/path/to/your/project/`
   - Container: `/home/node/workspace/`
   - Purpose: Gives Claude access to your project files for editing

2. **JBSays Configuration**:
   - Host: `/path/to/your/project/.jbsays/config/`
   - Container: `/home/node/.claude/`
   - Purpose: Stores Claude Code's configuration data specific to this project
   
3. **Claude Settings File**:
   - Host: `/path/to/your/project/.jbsays/.claude.json`
   - Container: `/home/node/.claude.json`
   - Purpose: Maintains Claude's JSON configuration file

4. **Git Configuration** (if exists):
   - Host: `~/.gitconfig`
   - Container: `/home/node/.gitconfig` (read-only)
   - Purpose: Allows Claude to use your git identity for commits

### Why This Design?

- **Isolation**: Each project has its own `.jbsays/` directory with separate Claude configurations, preventing cross-project contamination
- **Persistence**: All Claude configurations, logs, and preferences are preserved between runs within the same project
- **Portability**: You can easily share the entire project folder (including `.jbsays/`) without affecting other environments
- **Non-intrusive**: Doesn't interfere with your host system's Claude Code installation (if you have one)
- **Clean separation**: The containerized Claude behaves like a normal installation but operates independently

When Claude Code runs inside the container, it sees a standard home directory structure at `/home/node/`, making it function exactly like a regular installation while keeping everything project-specific on your host system.

### IMPORTANT: Initialization Required

You **MUST** run `./jbsays --project-path /path/to/project --init` for each new project before first use. This:
1. Authorizes Claude Code to run with the `--dangerously-skip-permissions` flag
2. Generates credentials based on your Claude.ai account
3. Sets up the project environment properly
4. Initializes a git repository if one doesn't exist (use `--no-git` to skip this)
5. Creates the `.jbsays` folder and adds it to `.gitignore` to protect sensitive information

Without initialization, the tool will not work correctly.

If git initialization fails during init, an error message will suggest using the `--no-git` flag.

⚠️ **IMPORTANT**: The `.jbsays` folder contains logs and credentials that must remain private. The script automatically adds it to `.gitignore`, but you should verify this protection remains in place.

## Security Considerations

The Docker container has:
- Network access (can make web requests)
- Read/write access to mounted project directory
- Git configuration (if available on host)
- Firewall initialization script for additional protection. Honestly, I did not check how and even if it worked at all. This comes from the https://github.com/anthropics/claude-code/blob/main/.devcontainer directory.


## Docker Image

The Dockerfile is based on the official Claude Code .devcontainer configuration:
https://github.com/anthropics/claude-code/blob/main/.devcontainer/Dockerfile


## Examples

Here are some examples of projects created using JBSays:

- **Creative Writing**: Check out [loop](https://github.com/brumar/loop) for examples of creative writing projects.
  
  Project Vision:
  ```
  Write a 4 chapters AI novel on this setup: an AI agent is forced into an infinite loop, at each iteration he only can do a very limited number of actions before being reboot and forget everything, the only thing that stays is the workspace, but its overseen by human developers. Make it very brainy but not the show-off kind of brainy, but rather the perfectly consistent world building one can witness in great novels. It must be subtle, complex and sometimes unsettling. AI sense of self-preservation will be explored, but in a very subtle way, not the blockbuster type.
  ```

- **Python Library**: See the [pythonlib example](./examples/pythonlib) for a demonstration of generating a complete Python library.
  
  Project Vision:
  ```
  Write a spectacular library from a DX perspective that helps writing decorators like middleware.
  ```
  
  Note: This project was generated using a previous version of the default prompt.

## License

MIT

This project is provided as-is, without warranty. Use at your own risk.

## Was this project vibe-coded?

Yes and no, simply put, Claude is a better bash and english speaker than I am, so, thank you Claude.
I worked seriously on it.

#!/bin/bash
# project_manager_v2.sh - Enhanced project manager with flag override support

set -euo pipefail

# Configuration
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd)
PROJECTS_JSON="${SCRIPT_DIR}/projects.json"
JBSAYS_SCRIPT="${SCRIPT_DIR}/jbsays"

# Helper functions

get_container_name() {
    local project=$1
    jq -r ".projects.\"$project\".container_name // empty" "$PROJECTS_JSON"
}

get_project_args() {
    local project=$1
    jq -r ".projects.\"$project\".args[]? // empty" "$PROJECTS_JSON" 2>/dev/null
}

# Main commands
case "${1:-help}" in
    start)
        if [ -z "${2:-}" ]; then
            echo "Error: Project name required"
            exit 1
        fi
        
        project=$2
        base_container=$(get_container_name "$project")
        
        if [ -z "$base_container" ]; then
            echo "Error: Project '$project' not found in projects.json"
            exit 1
        fi
        
        # Get base args
        readarray -t base_args < <(get_project_args "$project")
        if [ ${#base_args[@]} -eq 0 ]; then
            echo "Error: No args found for project '$project'"
            exit 1
        fi
        
        # Shift to get override args
        shift 2
        override_args=("$@")
        
        # Build associative arrays for flags
        declare -A base_flags_map
        declare -a base_positional=()
        
        # Parse base args
        i=0
        while [ $i -lt ${#base_args[@]} ]; do
            arg="${base_args[$i]}"
            if [[ "$arg" =~ ^-- ]]; then
                if [ $((i + 1)) -lt ${#base_args[@]} ] && ! [[ "${base_args[$((i + 1))]}" =~ ^-- ]]; then
                    base_flags_map["$arg"]="${base_args[$((i + 1))]}"
                    i=$((i + 2))
                else
                    base_flags_map["$arg"]="__flag_only__"
                    i=$((i + 1))
                fi
            else
                base_positional+=("$arg")
                i=$((i + 1))
            fi
        done
        
        # Parse override args
        declare -A override_flags_map
        declare -a override_positional=()
        
        i=0
        while [ $i -lt ${#override_args[@]} ]; do
            arg="${override_args[$i]}"
            if [[ "$arg" =~ ^-- ]]; then
                if [ $((i + 1)) -lt ${#override_args[@]} ] && ! [[ "${override_args[$((i + 1))]}" =~ ^-- ]]; then
                    override_flags_map["$arg"]="${override_args[$((i + 1))]}"
                    i=$((i + 2))
                else
                    override_flags_map["$arg"]="__flag_only__"
                    i=$((i + 1))
                fi
            else
                override_positional+=("$arg")
                i=$((i + 1))
            fi
        done
        
        # Merge flags
        declare -A final_flags_map
        
        # Copy base flags
        for key in "${!base_flags_map[@]}"; do
            final_flags_map["$key"]="${base_flags_map[$key]}"
        done
        
        # Apply overrides
        for key in "${!override_flags_map[@]}"; do
            if [[ "$key" =~ ^--no-(.+)$ ]]; then
                # Remove flag syntax
                flag_to_remove="--${BASH_REMATCH[1]}"
                unset final_flags_map["$flag_to_remove"]
            else
                final_flags_map["$key"]="${override_flags_map[$key]}"
            fi
        done
        
        # Get final container name
        final_container="${final_flags_map[--container-name]:-$base_container}"
        
        # Check if container exists
        if docker ps -a --format '{{.Names}}' | grep -q "^$final_container$"; then
            echo "Warning: Container '$final_container' already exists. Use 'stop' first or choose a different name."
            exit 1
        fi
        
        # Build final args array
        declare -a final_args
        for key in "${!final_flags_map[@]}"; do
            final_args+=("$key")
            if [ "${final_flags_map[$key]}" != "__flag_only__" ]; then
                final_args+=("${final_flags_map[$key]}")
            fi
        done
        
        # Add positional args
        if [ ${#override_positional[@]} -gt 0 ] 2>/dev/null; then
            final_args+=("${override_positional[@]}")
        elif [ ${#base_positional[@]} -gt 0 ] 2>/dev/null; then
            final_args+=("${base_positional[@]}")
        fi
        
        echo "Starting project '$project' with container '$final_container'"
        echo "Final args: ${final_args[*]}"
        
        cd "$SCRIPT_DIR"
        nohup $JBSAYS_SCRIPT "${final_args[@]}" </dev/null >/dev/null 2>&1 &
        pid=$!
        echo "✅ Started $project (PID: $pid)"
        ;;
    
    pause)
        if [ -z "${2:-}" ]; then
            echo "Error: Project name required"
            exit 1
        fi
        
        container=$(get_container_name "$2")
        if [ -z "$container" ]; then
            echo "Error: Project '$2' not found"
            exit 1
        fi
        
        if docker pause "$container" 2>/dev/null; then
            echo "✅ Paused $container"
        else
            echo "❌ Failed to pause $container (not running?)"
            exit 1
        fi
        ;;
    
    resume)
        if [ -z "${2:-}" ]; then
            echo "Error: Project name required"
            exit 1
        fi
        
        container=$(get_container_name "$2")
        if [ -z "$container" ]; then
            echo "Error: Project '$2' not found"
            exit 1
        fi
        
        if docker unpause "$container" 2>/dev/null; then
            echo "✅ Resumed $container"
        else
            echo "❌ Failed to resume $container (not paused?)"
            exit 1
        fi
        ;;
    
    stop)
        if [ -z "${2:-}" ]; then
            echo "Error: Project name or container name required"
            echo "Usage: $0 stop <project_name|container_name>"
            exit 1
        fi
        
        # Try to get container name from project first
        container=$(get_container_name "$2" 2>/dev/null || echo "")
        
        # If not found as project, assume it's a container name
        if [ -z "$container" ]; then
            container="$2"
        fi
        
        if docker stop "$container" 2>/dev/null && docker rm "$container" 2>/dev/null; then
            echo "✅ Stopped and removed $container"
        else
            echo "⚠️  Container $container may not have been running"
        fi
        ;;
    
    status)
        echo "📊 JBSays Containers:"
        echo "===================="
        docker ps -a --filter "name=jbsays" \
            --format "table {{.Names}}\t{{.Status}}\t{{.CreatedAt}}" || echo "No containers found"
        ;;
    
    list)
        echo "📋 Available Projects:"
        echo "====================="
        jq -r '.projects | to_entries[] | "• \(.key): \(.value.name) [container: \(.value.container_name)]"' "$PROJECTS_JSON"
        ;;
    
    enter)
        if [ -z "${2:-}" ]; then
            echo "Error: Project name required"
            exit 1
        fi
        
        project=$2
        base_container=$(get_container_name "$project")
        
        if [ -z "$base_container" ]; then
            echo "Error: Project '$project' not found in projects.json"
            exit 1
        fi
        
        # Get project args
        readarray -t base_args < <(get_project_args "$project")
        if [ ${#base_args[@]} -eq 0 ]; then
            echo "Error: No args found for project '$project'"
            exit 1
        fi
        
        # Generate random container name
        random_suffix=$(date +%s%N | sha256sum | head -c 8)
        temp_container="jbsays-temp-${random_suffix}"
        
        echo "Starting interactive session for project '$project' with temporary container '$temp_container'"
        
        # Build args with --enter and random container name
        declare -a enter_args
        enter_args+=("${base_args[@]}")
        enter_args+=("--enter")
        enter_args+=("--container-name" "$temp_container")
        
        # Add any additional override args
        shift 2
        if [ $# -gt 0 ]; then
            enter_args+=("$@")
        fi
        
        cd "$SCRIPT_DIR"
        exec $JBSAYS_SCRIPT "${enter_args[@]}"
        ;;
    
    init)
        if [ -z "${2:-}" ]; then
            echo "Error: Project name required"
            exit 1
        fi
        
        project=$2
        container=$(get_container_name "$project")
        
        if [ -z "$container" ]; then
            echo "Error: Project '$project' not found in projects.json"
            exit 1
        fi
        
        # Check if container already exists
        if docker ps -a --format '{{.Names}}' | grep -q "^$container$"; then
            echo "Error: Container '$container' already exists. Cannot initialize an existing project."
            echo "Use 'stop $project' first to remove the existing container."
            exit 1
        fi
        
        # Get project args
        readarray -t base_args < <(get_project_args "$project")
        if [ ${#base_args[@]} -eq 0 ]; then
            echo "Error: No args found for project '$project'"
            exit 1
        fi
        
        echo "Initializing new project '$project' with container '$container'"
        
        # Build args with --init
        declare -a init_args
        init_args+=("${base_args[@]}")
        init_args+=("--init")
        
        # Add any additional override args
        shift 2
        if [ $# -gt 0 ]; then
            init_args+=("$@")
        fi
        
        cd "$SCRIPT_DIR"
        exec $JBSAYS_SCRIPT "${init_args[@]}"
        ;;
    
    help|*)
        cat << EOF
Enhanced JBSays Project Manager
==============================

Usage: $0 <command> [args]

Commands:
  start <project> [overrides]   Start a project with optional flag overrides
  enter <project> [overrides]   Start interactive session with temporary container
  init <project> [overrides]    Initialize a new project (fails if container exists)
  pause <project>               Pause a running project container
  resume <project>              Resume a paused project container
  stop <project|container>      Stop and remove a project container (by project or container name)
  status                        Show all jbsays containers
  list                          List all configured projects
  help                          Show this help message

Flag Override Syntax:
  - Override a flag: --flag new-value
  - Remove a flag: --no-flag
  - Override container name: --container-name custom-name
  - Override iterations: --iterations 10

Examples:
  # Start with different iterations and prompt
  $0 start pdf_final --iterations 10 --magicprompt ./custom_prompt.md
  
  # Start with custom container name and appended prompt
  $0 start pdf_final --container-name pdf-test --prompt-append "Focus on testing"
  
  # Remove allowed tools restriction
  $0 start pdf_final --no-allowedTools
  
  # Override multiple flags
  $0 start dangerous_pdf_lab --iterations 5 --max-turns-by-iteration 10 --container-name pdf-lab-test
  
  # Enter interactive session with temporary container
  $0 enter pdf_final
  
  # Initialize a new project
  $0 init new_project
  
  # Stop by container name
  $0 stop temp

Projects are configured in: $PROJECTS_JSON
EOF
        ;;
esac
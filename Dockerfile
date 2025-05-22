# Multi-stage build for extensibility
FROM node:20 as base

# Timezone setup (optional)
ARG TZ=Etc/UTC
ENV TZ="$TZ"

RUN npm install -g @playwright/mcp@latest

# Install Chrome browser and dependencies required by Playwright
# Although the base image should include them, explicitly install in case MCP cannot find them
RUN npx playwright install chrome && npx playwright install-deps chrome

# Install dev tools, CLI utilities, and tools for agent operation
RUN apt-get update && apt-get install -y \
  git procps sudo fzf zsh man-db unzip gnupg2 \
  gh iptables ipset iproute2 dnsutils aggregate jq \
  wget curl less \
  gettext-base ca-certificates \
  qpdf mupdf-tools \
  && apt-get clean

# Install git-delta (nicer git diffs) - Optional, can be removed if not strictly needed for Claude
RUN ARCH=$(dpkg --print-architecture) && \
  wget "https://github.com/dandavison/delta/releases/download/0.18.2/git-delta_0.18.2_${ARCH}.deb" && \
  dpkg -i "git-delta_0.18.2_${ARCH}.deb" && \
  rm "git-delta_0.18.2_${ARCH}.deb"

# Base image node:20 already has a 'node' user.
# We'll use that user. Let's find its UID/GID to be sure,
# or assume it's 1000 (common for 'node' images)
# For this example, we'll assume the existing 'node' user is sufficient.

# This ARG is still useful for referencing the username
ARG USERNAME=node 

# Ensure directories needed by the 'node' user exist and have correct ownership
# No need to create the user/group if it already exists from the base image.
RUN mkdir -p /usr/local/share/npm-global && \
    chown -R $USERNAME:$USERNAME /usr/local/share/npm-global && \
    # Create .claude and .claude.json placeholders for mounting/use by the 'node' user
    # The home directory for the 'node' user in official images is usually /home/node
    mkdir -p /home/$USERNAME/.claude && \
    touch /home/$USERNAME/.claude.json && \
    chown -R $USERNAME:$USERNAME /home/$USERNAME/.claude /home/$USERNAME/.claude.json && \
    # Create workspace within user's home directory
    mkdir -p /home/$USERNAME/workspace && \
    chown -R $USERNAME:$USERNAME /home/$USERNAME/workspace

# (The rest of your Dockerfile related to history, Zsh, npm install claude-code, etc.)
# Make sure these subsequent steps correctly use USER $USERNAME where appropriate.


# Add safe bash history persistence (Zsh history will be handled by zsh-in-docker)
# This bash history setup is less relevant if default shell is zsh and zsh-in-docker is used.
# Consider removing if focusing purely on zsh.
RUN mkdir /commandhistory && touch /commandhistory/.bash_history && \
  chown -R $USERNAME:$USERNAME /commandhistory
# for bash
ENV PROMPT_COMMAND='history -a' 
ENV HISTFILE=/commandhistory/.bash_history

# Default WORKDIR for Claude operations
WORKDIR /home/$USERNAME/workspace 

# Set default shell for user
ENV SHELL /bin/zsh

# Setup Zsh and powerline prompt (for a nice interactive experience)
# This will also configure Zsh history persistence.
RUN sh -c "$(wget -O- https://github.com/deluan/zsh-in-docker/releases/download/v1.2.0/zsh-in-docker.sh)" -- \
  -u $USERNAME \
  -p git -p fzf \
  -a "source /usr/share/doc/fzf/examples/key-bindings.zsh" \
  -a "source /usr/share/doc/fzf/examples/completion.zsh" \
  -x

# Install Claude Code CLI
# Ensure NPM_CONFIG_PREFIX is set correctly for the USER context
USER $USERNAME
ENV NPM_CONFIG_PREFIX=/usr/local/share/npm-global
ENV PATH=$PATH:/usr/local/share/npm-global/bin
RUN npm install -g @anthropic-ai/claude-code

# Set container name as environment variable
ENV CONTAINER_NAME=jbsays

# Copy MCP configuration
COPY .mcp.json /home/$USERNAME/workspace/.mcp.json

# Switch back to root for any further root-level operations if needed
USER root 

RUN chown $USERNAME:$USERNAME /home/$USERNAME/workspace/.mcp.json

# Copy default prompt template into the image

# Firewall setup (optional, original from your Dockerfile)
# If init-firewall.sh is specific to this project, COPY it.
COPY init-firewall.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/init-firewall.sh && \
  echo "$USERNAME ALL=(root) NOPASSWD: /usr/local/bin/init-firewall.sh" > /etc/sudoers.d/node-firewall && \
  chmod 0440 /etc/sudoers.d/node-firewall

# Set user and default command
USER $USERNAME
# Default WORKDIR for both interactive and agent modes
WORKDIR /home/$USERNAME/workspace 

# Default command: launch claude CLI directly.
# This makes `docker run <image_name>` drop into claude interactive mode.
# For agent mode, iteration.sh will override this CMD.
CMD ["claude", "--dangerously-skip-permissions"]

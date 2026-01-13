# azure-ai-foundry-agent

## Overview

The `azure-ai-foundry-agent` is a Python-based Azure Function application that uses the **Microsoft Foundry Agent Framework SDK** (`agent-framework-azure-ai`) to create and interact with AI Foundry agents dynamically. It provides an HTTP-triggered endpoint for processing user messages and generating responses using ephemeral AI agents.

This application is built to:
1. Handle user requests with message input and optional agent configuration.
2. Create AI agents on-demand using the Foundry Agent Framework.
3. Process user messages through the agent's conversational interface.
4. Generate intelligent responses based on configurable agent instructions.

## Features

- **HTTP Trigger**: Provides an anonymous endpoint `/agent_httptrigger` to accept user inputs.
- **Microsoft Foundry Agent Framework**: Uses the preview `agent-framework-azure-ai` SDK to create and manage AI agents dynamically.
- **Flexible Agent Configuration**: Supports custom agent names, instructions, and model deployments.
- **Conversation Continuity**: Manages thread serialization for multi-turn conversations.
- **Error Handling**: Includes robust error checking and logging to ensure smooth operation.

## Prerequisites

To run this project, ensure that you have:
1. Azure Functions Core Tools installed.
2. Python 3.9 or later (required for agent-framework-azure-ai).
3. Required libraries listed in `requirements.txt` (install with `--pre` flag for preview packages).
4. Azure AI Foundry project with a deployed model.
5. Azure Subscription with appropriate permissions.

## Installation

1. Clone the repository:
    ```bash
    git clone https://github.com/azure-data-ai-hub/azure-ai-foundry-agent.git
    cd azure-ai-foundry-agent
    ```

2. Install dependencies (note the `--pre` flag for preview packages):
    ```bash
    pip install --pre -r requirements.txt
    ```

3. Set up environment variables in `local.settings.json`:
    - `AIProjectEndpoint`: Your Azure AI Foundry project endpoint (e.g., `https://your-project.services.ai.azure.com/api/projects/your-project`)
    - `ModelDeploymentName`: Model deployment name (e.g., `gpt-4o-mini`)

4. Authenticate with Azure:
    ```bash
    az login
    ```

5. Run the Azure Function locally:
    ```bash
    func start
    ```

## HTTP Trigger Details

### Endpoint

`POST /agent_httptrigger`

### Query Parameters

| Name           | Type   | Description                                                      |
|----------------|--------|------------------------------------------------------------------|
| `message`      | string | **Required.** The user message to process.                      |
| `agent_name`   | string | (Optional) Name of the agent to create. Default: "AssistantAgent" |
| `instructions` | string | (Optional) Custom instructions for the agent. Default: "You are a helpful assistant." |
| `threadid`     | string | (Optional) Thread ID for conversation continuity (future use).   |

### Request Example

```json
{
  "message": "Hello, AI Agent!",
  "agent_name": "MyCustomAgent",
  "instructions": "You are a friendly assistant who speaks in a casual tone."
}

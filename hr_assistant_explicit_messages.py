"""
HR Assistant with Explicit System and User Messages

This example demonstrates how to send a system message first with rendered
user-specific variables, followed by the user's query message.

This pattern gives you more control over the conversation flow and allows
you to inject user context as a system message before each interaction.
"""

import asyncio
import json
import os
from pathlib import Path
from agent_framework.azure import AzureAIClient
from agent_framework import ChatMessage, Role
from azure.identity.aio import DefaultAzureCredential


def load_openapi_spec(spec_file_path: str | Path) -> dict:
    """Load an OpenAPI specification from a JSON or YAML file."""
    spec_path = Path(spec_file_path)
    
    if not spec_path.exists():
        raise FileNotFoundError(f"OpenAPI spec file not found: {spec_path}")
    
    with open(spec_path, "r", encoding="utf-8") as f:
        if spec_path.suffix.lower() in [".yaml", ".yml"]:
            import yaml
            return yaml.safe_load(f)
        else:
            return json.load(f)


def create_system_instructions(user_id: str, user_full_name: str) -> str:
    """
    Create the system instructions with user-specific variables rendered.
    
    Args:
        user_id: The user's ID (e.g., "JDOE")
        user_full_name: The user's full name in "Last, First" format
    
    Returns:
        Rendered system instructions string
    """
    return f"""You are an HR assistant. 

When users ask about HR benefits information (pay, vacation balance, health/dental/vision plans), and when users ask about HR profile information (employee id, supervisor/manager name, contact information, address, title, hire date, level/grade, job title):
- Call the 'hr_info_given_userid' tool with user_name: {user_id}

# Rules when answering questions
- Be brief in your answers.
- Use the benefits tool 'hr_info_given_userid' to get specific employee enrollment and personal data
- Combine information from all tools when needed to provide comprehensive answers
- ALWAYS refer to the provided tools for accurate and up-to-date information. If information is not available to answer the question, say I don't know.
- DO NOT USE your own general knowledge to generate answers.
- If asking a clarifying question to the user would help, ask the question.
- Use the user's name "{user_full_name}" to personalize the conversation. User's name is in the format of <last name, first name>
"""


async def hr_assistant_with_explicit_messages(
    user_id: str,
    user_full_name: str,
    user_query: str,
    openapi_spec_path: str | Path = "hr_api_spec.json"
):
    """
    Run HR assistant by explicitly sending system message first, then user message.
    
    This approach:
    1. Creates an agent with base instructions
    2. Sends a system message with user-specific context
    3. Sends the user's query as a separate user message
    
    Args:
        user_id: The user's ID
        user_full_name: The user's full name
        user_query: The user's question
        openapi_spec_path: Path to the OpenAPI spec file
    """
    
    # Render the system instructions with user-specific variables
    effective_instructions = create_system_instructions(user_id, user_full_name)
    
    # Load the OpenAPI specification
    hr_api_spec = load_openapi_spec(openapi_spec_path)
    
    project_endpoint = os.getenv("FOUNDRY_PROJECT_ENDPOINT")
    model_deployment = os.getenv("FOUNDRY_MODEL_DEPLOYMENT")

    async with (
        DefaultAzureCredential() as credential,
        AzureAIClient(
            project_endpoint=project_endpoint,
            model_deployment_name=model_deployment,
            credential=credential,
        ).create_agent(
            name="HRAssistantExplicitMessages",
            instructions="You are a helpful HR assistant.",  # Base instructions
            tools={
                "type": "openapi",
                "openapi": {
                    "name": "hr_info_given_userid",
                    "spec": hr_api_spec,
                    "description": "Get HR benefits and profile information for an employee",
                    "auth": {"type": "anonymous"},
                },
            },
        ) as agent,
    ):
        # Create a new thread for this conversation
        thread = agent.get_new_thread()
        
        # Method 1: Using run() with a list of messages
        # This sends system message first, then user message
        messages = [
            ChatMessage(role="system", text=effective_instructions),
            ChatMessage(role="user", text=user_query),
        ]
        
        print(f"User ({user_full_name}): {user_query}")
        print("HR Assistant: ", end="", flush=True)
        
        # Run with explicit message list
        async for chunk in agent.run_stream(messages, thread=thread):
            if chunk.text:
                print(chunk.text, end="", flush=True)
        print("\n")
        
        return thread


async def hr_assistant_multi_turn_with_system_context(
    user_id: str,
    user_full_name: str,
    openapi_spec_path: str | Path = "hr_api_spec.json"
):
    """
    Interactive multi-turn conversation where system context is sent first,
    then user messages are added to the same thread.
    """
    
    effective_instructions = create_system_instructions(user_id, user_full_name)
    hr_api_spec = load_openapi_spec(openapi_spec_path)
    
    project_endpoint = os.getenv("FOUNDRY_PROJECT_ENDPOINT")
    model_deployment = os.getenv("FOUNDRY_MODEL_DEPLOYMENT")

    async with (
        DefaultAzureCredential() as credential,
        AzureAIClient(
            project_endpoint=project_endpoint,
            model_deployment_name=model_deployment,
            credential=credential,
        ).create_agent(
            name="HRAssistantMultiTurn",
            instructions="You are a helpful HR assistant.",
            tools={
                "type": "openapi",
                "openapi": {
                    "name": "hr_info_given_userid",
                    "spec": hr_api_spec,
                    "description": "Get HR benefits and profile information for an employee",
                    "auth": {"type": "anonymous"},
                },
            },
        ) as agent,
    ):
        thread = agent.get_new_thread()
        
        # Send system message first to establish user context
        system_message = ChatMessage(role="system", text=effective_instructions)
        await agent.run(system_message, thread=thread)
        
        print(f"\nWelcome to HR Assistant, {user_full_name.split(', ')[1]}!")
        print("System context has been set with your user information.")
        print("Type 'quit' to exit.\n")
        
        while True:
            user_input = input("You: ").strip()
            if user_input.lower() in ['quit', 'exit', 'q']:
                print("Goodbye!")
                break
            
            if not user_input:
                continue
            
            # Send user message (system context is already in thread)
            user_message = ChatMessage(role="user", text=user_input)
            
            print("HR Assistant: ", end="", flush=True)
            async for chunk in agent.run_stream(user_message, thread=thread):
                if chunk.text:
                    print(chunk.text, end="", flush=True)
            print("\n")


async def demo_explicit_messages():
    """Demo showing explicit system + user message pattern."""
    
    openapi_spec_path = "hr_api_spec.json"
    
    # User examples
    users_and_queries = [
        {
            "user_id": "SHSU",
            "full_name": "HSU, Susan",
            "query": "Who is my manager?"
        },
        {
            "user_id": "SCHOY",
            "full_name": "Choy, Steven",
            "query": "Who is my manager?"
        },
    ]
    
    for user in users_and_queries:
        print(f"\n{'='*60}")
        print(f"Session for: {user['full_name']} (ID: {user['user_id']})")
        print('='*60)
        
        await hr_assistant_with_explicit_messages(
            user_id=user['user_id'],
            user_full_name=user['full_name'],
            user_query=user['query'],
            openapi_spec_path=openapi_spec_path
        )


if __name__ == "__main__":
    print("=== HR Assistant with Explicit System/User Messages ===")
    print("This demo sends system message first, then user query.\n")
    
    asyncio.run(demo_explicit_messages())
    
    # Uncomment for interactive multi-turn session:
    # print("\n=== Interactive Session with System Context ===")
    # asyncio.run(hr_assistant_multi_turn_with_system_context(
    #     user_id="JDOE",
    #     user_full_name="Doe, John"
    # ))

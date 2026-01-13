import azure.functions as func
import logging
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from agent_framework.azure import AzureAIClient
from azure.identity.aio import DefaultAzureCredential as AsyncDefaultAzureCredential
import os
import json
import asyncio

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

@app.route(route="agent_httptrigger")
def agent_httptrigger(req: func.HttpRequest) -> func.HttpResponse:
    """
    HTTP trigger function that creates and interacts with AI Foundry agents using the 
    Microsoft Foundry Agent Framework SDK (agent-framework-azure-ai).
    
    Parameters (query string or JSON body):
        - message: User message to send to the agent
        - agent_name: Name of the agent to create (optional, defaults to 'AssistantAgent')
        - instructions: Custom instructions for the agent (optional)
        - threadid: Existing thread ID for conversation continuity (optional)
    """
    logging.info('Python HTTP trigger function processed a request.')

    message = req.params.get('message')
    agent_name = req.params.get('agent_name')
    instructions = req.params.get('instructions')
    threadid = req.params.get('threadid')
    
    if not message:
        try:
            req_body = req.get_json()
        except ValueError:
            req_body = None

        if req_body:
            message = req_body.get('message')
            agent_name = req_body.get('agent_name')
            instructions = req_body.get('instructions')
            threadid = req_body.get('threadid')

    if not message:
        return func.HttpResponse(
            json.dumps({
                "error": "Missing required parameter 'message'",
                "usage": "Provide 'message' in query string or request body. Optional: 'agent_name', 'instructions', 'threadid'"
            }),
            status_code=400,
            mimetype="application/json"
        )

    # Set defaults
    agent_name = agent_name or "AssistantAgent"
    instructions = instructions or "You are a helpful assistant."
    
    endpoint = os.environ.get("AIProjectEndpoint")
    model_deployment = os.environ.get("ModelDeploymentName", "gpt-4o-mini")
    agent_id = os.environ.get("AGENT_ID")  # Optional: use existing agent instead of creating ephemeral ones
    
    # If no AGENT_ID in env but agent_name is provided in request with PERSIST_AGENT=true,
    # the function will find/create agent by that name
    
    if not endpoint:
        logging.error("AIProjectEndpoint must be set in environment variables.")
        return func.HttpResponse(
            json.dumps({"error": "Server configuration error: Missing AIProjectEndpoint"}),
            status_code=500,
            mimetype="application/json"
        )

    try:
        # Run the async agent interaction
        result = asyncio.run(_interact_with_agent(
            endpoint=endpoint,
            model_deployment=model_deployment,
            agent_name=agent_name,
            instructions=instructions,
            user_message=message,
            thread_id=threadid,
            agent_id=agent_id
        ))
        
        return func.HttpResponse(
            json.dumps(result, ensure_ascii=False),
            status_code=200,
            mimetype="application/json",
            charset="utf-8"
        )
    except Exception as e:
        logging.error(f"An error occurred: {str(e)}")
        import traceback
        logging.error(traceback.format_exc())
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )


async def _interact_with_agent(
    endpoint: str,
    model_deployment: str,
    agent_name: str,
    instructions: str,
    user_message: str,
    thread_id: str = None,
    agent_id: str = None
) -> dict:
    """
    Creates or uses an AI Foundry agent using the Microsoft Foundry Agent Framework SDK
    and processes a user message.
    
    Three modes:
    1. If agent_id is provided (from env AGENT_ID), uses that specific agent (persistent).
    2. If PERSIST_AGENT=true in env, finds/creates agent by agent_name (persistent, can use request param).
    3. Otherwise, creates ephemeral agents that are automatically cleaned up after use.
    """
    from azure.ai.agents.aio import AgentsClient
    
    persist_agent = os.environ.get("PERSIST_AGENT", "false").lower() == "true"
    
    async with AsyncDefaultAzureCredential() as credential:
        if agent_id:
            # Mode 1: Use existing persistent agent by ID
            async with AzureAIClient(
                project_endpoint=endpoint,
                model_deployment_name=model_deployment,
                credential=credential,
            ).create_agent(
                agent_id=agent_id,
                name=agent_name,
                instructions=instructions
            ) as agent:
                logging.info(f"Using existing agent: {agent_id}")
                return await _process_agent_message(agent, user_message, thread_id, agent_name, model_deployment, agent_id)
        elif persist_agent:
            # Mode 2: Create or retrieve persistent agent by name (from request or default)
            async with AgentsClient(endpoint=endpoint, credential=credential) as agents_client:
                # Try to find existing agent by name
                existing_agent = await _find_agent_by_name(agents_client, agent_name)
                
                if existing_agent:
                    logging.info(f"Found existing persistent agent: {existing_agent.id} (name: {agent_name})")
                    agent_id_to_use = existing_agent.id
                else:
                    # Create new persistent agent with provided name and instructions
                    new_agent = await agents_client.create_agent(
                        model=model_deployment,
                        name=agent_name,
                        instructions=instructions
                    )
                    logging.info(f"Created new persistent agent: {new_agent.id} (name: {agent_name})")
                    agent_id_to_use = new_agent.id
                
                # Use the persistent agent via AzureAIClient
                async with AzureAIClient(
                    project_endpoint=endpoint,
                    model_deployment_name=model_deployment,
                    credential=credential,
                ).create_agent(
                    agent_id=agent_id_to_use,
                    name=agent_name,
                    instructions=instructions
                ) as agent:
                    return await _process_agent_message(agent, user_message, thread_id, agent_name, model_deployment, agent_id_to_use)
        else:
            # Mode 3: Create ephemeral agent (will be deleted after use)
            async with AzureAIClient(
                project_endpoint=endpoint,
                model_deployment_name=model_deployment,
                credential=credential,
            ).create_agent(
                name=agent_name,
                instructions=instructions
            ) as agent:
                logging.info(f"Created ephemeral agent: {agent_name}")
                return await _process_agent_message(agent, user_message, thread_id, agent_name, model_deployment, None)


async def _find_agent_by_name(agents_client, agent_name: str):
    """Find an existing agent by name."""
    try:
        agents = agents_client.list_agents()
        async for agent in agents:
            if agent.name == agent_name:
                return agent
    except Exception as e:
        logging.warning(f"Error listing agents: {e}")
    return None


async def _process_agent_message(agent, user_message: str, thread_id: str, agent_name: str, model_deployment: str, agent_id: str = None) -> dict:
    """Process a message with the agent."""
    # Handle thread continuation or create new thread
    if thread_id:
        logging.info(f"Thread ID provided but creating new conversation context: {thread_id}")
        thread = agent.get_new_thread()
    else:
        thread = agent.get_new_thread()
    
    # Run the agent with the user message
    result = await agent.run(user_message, thread=thread)
    
    # Serialize thread for potential continuation
    thread_data = await thread.serialize()
    
    response = {
        "message": result.text,
        "threadId": thread_data.get("id", "new"),
        "agentName": agent_name,
        "model": model_deployment
    }
    
    if agent_id:
        response["agentId"] = agent_id
    
    return response

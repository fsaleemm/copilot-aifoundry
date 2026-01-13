import azure.functions as func
import logging
from agent_framework.azure import AzureAIClient
from azure.identity.aio import DefaultAzureCredential as AsyncDefaultAzureCredential
import os
import json
import asyncio
from pathlib import Path

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

@app.route(route="agent_httptrigger")
def agent_httptrigger(req: func.HttpRequest) -> func.HttpResponse:
    """
    HTTP trigger function that creates and interacts with AI Foundry agents using the 
    Microsoft Foundry Agent Framework SDK (agent-framework-azure-ai).
    
    Parameters (query string or JSON body):
        - message: User message to send to the agent (required)
        - agent_name: Name of the agent to create (optional, defaults to 'AssistantAgent')
        - instructions: Custom instructions for the agent (optional)
        - threadid: Existing thread ID for conversation continuity (optional)
        - parameters: JSON object with name-value pairs for instruction template substitution (optional)
    
    Environment Variables:
        - AGENT_INSTRUCTIONS_TEMPLATE: Template string with {variable} placeholders (optional)
          Example: "You are an HR assistant. User: {user_name} (ID: {user_id})"
        - PERSIST_AGENT: Set to 'true' to persist agents by name
        - AGENT_ID: Specific agent ID to use (overrides PERSIST_AGENT)
    """
    logging.info('Python HTTP trigger function processed a request.')

    message = req.params.get('message')
    agent_name = req.params.get('agent_name')
    instructions = req.params.get('instructions')
    threadid = req.params.get('threadid')
    parameters = None
    
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
            parameters = req_body.get('parameters')  # JSON object with name-value pairs

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
    
    # Handle instruction templates from environment variables
    instruction_template = os.environ.get("AGENT_INSTRUCTIONS_TEMPLATE")
    if instruction_template and parameters:
        # Use template with variable substitution
        try:
            instructions = instruction_template.format(**parameters)
            logging.info(f"Applied instruction template with parameters: {list(parameters.keys())}")
        except KeyError as e:
            return func.HttpResponse(
                json.dumps({
                    "error": f"Missing required parameter for instruction template: {str(e)}",
                    "template_variables": list(parameters.keys()) if parameters else []
                }),
                status_code=400,
                mimetype="application/json"
            )
    else:
        # Use provided instructions or default
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


async def _interact_with_agent(
    endpoint: str,
    model_deployment: str,
    agent_name: str,
    instructions: str,
    user_message: str,
    thread_id: str = None,
    agent_id: str = None,
    openapi_spec_path: str | Path = "hr_api_spec.json"
) -> dict:
    """
    Uses an existing AI Foundry agent by ID and processes a user message.
    
    The agent must already exist in Azure AI Foundry. Provide agent_id via:
    - Query parameter: agentid
    - Environment variable: AGENT_ID
    
    Instructions are optional runtime overrides and don't modify the agent definition.
    """
    
    if not agent_id:
        raise ValueError("agent_id is required. Provide it via 'agentid' parameter or AGENT_ID environment variable.")
    
    hr_api_spec = load_openapi_spec(openapi_spec_path)
    
    async with AsyncDefaultAzureCredential() as credential:
        try:
            # Use existing agent by ID - preserves all tools and KBs
            # Instructions are runtime overrides only
            async with AzureAIClient(
                project_endpoint=endpoint,
                model_deployment_name=model_deployment,
                credential=credential,
            ).create_agent(
                agent_id=agent_id,
                name=agent_name,
                instructions=instructions if instructions else None,
                tools={
                "type": "openapi",
                "openapi": {
                    "name": "hr_info_given_userid",
                    "spec": hr_api_spec,
                    "description": "Get HR benefits and profile information for an employee",
                    "auth": {"type": "anonymous"},
                    },
                },
            ) as agent:
                logging.info(f"Using existing agent: {agent_id}")
                return await _process_agent_message(agent, user_message, thread_id, agent_name, model_deployment, agent_id)
        except Exception as e:
            error_msg = str(e)
            if "not found" in error_msg.lower() or "404" in error_msg or "does not exist" in error_msg.lower():
                raise ValueError(f"Agent with ID '{agent_id}' does not exist in the Azure AI Foundry project. Please verify the agent ID.")
            raise



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

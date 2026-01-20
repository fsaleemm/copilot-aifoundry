import azure.functions as func
import logging
from agent_framework.azure import AzureAIClient
from azure.identity.aio import DefaultAzureCredential as AsyncDefaultAzureCredential
from azure.identity import DefaultAzureCredential
import os
import json
import asyncio
from pathlib import Path
from azure.ai.projects import AIProjectClient

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
        project_client = AIProjectClient(
            endpoint=endpoint,
            credential=DefaultAzureCredential(),
        )

        # Get an existing agent
        agent = project_client.agents.get(agent_name=agent_id)

        # Get the OpenAI client for responses
        openai_client = project_client.get_openai_client()

        if threadid:
            # Continue existing conversation
            conversation_id = threadid
            # get the conversation to ensure it exists
            conversation = openai_client.conversations.retrieve(conversation_id)

            # Add the new user message to the existing conversation
            openai_client.conversations.items.create(
                conversation_id=conversation_id,
                items=[{"type": "message", "role": "user", "content": message}]
            )
            
        else:
            # Create a conversation for context persistence
            conversation = openai_client.conversations.create(
                items=[{"type": "message", "role": "system", "content": instructions},
                    {"type": "message", "role": "user", "content": message}],
            )

            conversation_id = conversation.id
        
        response = openai_client.responses.create(
            conversation=conversation_id,
            input="",  # Empty since we already added the message to the conversation
            extra_body={
                "agent": {"type": "agent_reference", "name": agent.name},
            }
        )

        result = {
        "message": response.output_text,
        "threadId": response.conversation.id
        }


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

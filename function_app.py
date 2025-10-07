import azure.functions as func
import logging
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
import os
import json

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

@app.route(route="agent_httptrigger")
def agent_httptrigger(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request.')

    message = req.params.get('message')
    agentid = req.params.get('agentid')
    threadid = req.params.get('threadid')
    
    if not message or not agentid:
        try:
            req_body = req.get_json()
        except ValueError:
            req_body = None

        if req_body:
            message = req_body.get('message')
            agentid = req_body.get('agentid')
            threadid = req_body.get('threadid')

    if not message or not agentid:
        return func.HttpResponse(
            "Pass in a message and agentid in the query string or in the request body for a personalized response.",
            status_code=400
        )

    endpoint = os.environ.get("AIProjectEndpoint")
    
    if not endpoint:
        logging.error("AIProjectEndpoint must be set in environment variables.")
        return func.HttpResponse(
            "Internal Server Error: Missing AIProjectEndpoint configuration.",
            status_code=500
        )

    try:
        # Use endpoint-based authentication (SDK 1.0+)
        project_client = AIProjectClient(
            endpoint=endpoint,
            credential=DefaultAzureCredential(),
        )

        agent = project_client.agents.get_agent(agentid)
        if not agent:
            logging.error(f"Agent with ID {agentid} not found.")
            return func.HttpResponse(
                f"Agent with ID {agentid} not found.",
                status_code=404
            )

        # Create or use existing thread
        if not threadid:
            # Create a new thread using the SDK 1.0+ API
            thread_response = project_client.agents.threads.create()
            thread_id = thread_response.id
        else:
            thread_id = threadid
            
        # Create a message in the thread (using SDK 1.0+ API)
        message = project_client.agents.messages.create(
            thread_id=thread_id,
            role="user",
            content=message
        )

        # Process the message with the agent (using SDK 1.0+ API)
        project_client.agents.runs.create_and_process(
            thread_id=thread_id,
            agent_id=agent.id
        )

        # Get the messages from the thread (using SDK 1.0+ API)
        messages = project_client.agents.messages.list(thread_id=thread_id)
        
        # Extract the latest assistant message
        assistant_text = ""
        
        # Iterate through messages to find the latest assistant message
        for msg in messages:
            if msg.role == "assistant":
                # Use the new text_messages property for easier access
                if hasattr(msg, 'text_messages') and msg.text_messages:
                    # Get the latest text message
                    latest_text = msg.text_messages[-1]
                    assistant_text = latest_text.text.value
                elif hasattr(msg, 'content') and msg.content:
                    # Fallback to content parsing if text_messages not available
                    text_parts = []
                    for part in msg.content:
                        if hasattr(part, 'type') and part.type == 'text' and hasattr(part, 'text'):
                            text_parts.append(part.text.value)
                    assistant_text = " ".join(text_parts) if text_parts else "No text content found."
                break
        
        if not assistant_text:
            assistant_text = "No assistant message found."

        # Return the response with the thread ID for continuity
        response_data = {
            "message": assistant_text,
            "threadId": thread_id
        }
        
        return func.HttpResponse(
            json.dumps(response_data, ensure_ascii=False),
            status_code=200,
            mimetype="application/json",
            charset="utf-8"
        )
    except Exception as e:
        logging.error(f"An error occurred: {str(e)}")
        # Include more detailed error information for debugging
        import traceback
        logging.error(traceback.format_exc())
        return func.HttpResponse(
            "Internal Server Error: " + str(e),
            status_code=500
        )

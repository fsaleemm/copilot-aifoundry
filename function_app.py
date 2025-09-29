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

    conn_str = os.environ.get("AIProjectConnString")
    if not conn_str:
        logging.error("AIProjectConnString is not set in local.settings.json or environment variables.")
        return func.HttpResponse(
            "Internal Server Error: Missing AIProjectConnString.",
            status_code=500
        )

    try:            
        project_client = AIProjectClient.from_connection_string(
            credential=DefaultAzureCredential(),
            conn_str=conn_str,
        )

        agent = project_client.agents.get_agent(agentid)
        if not agent:
            logging.error(f"Agent with ID {agentid} not found.")
            return func.HttpResponse(
                f"Agent with ID {agentid} not found.",
                status_code=404
            )

        # Fix for the 'create_thread' method issue
        if not threadid:
            # Create a new thread using the correct API
            try:
                # Try the newer API if available
                thread_response = project_client.agents.create_thread()
                thread_id = thread_response.id
            except AttributeError:
                # Fallback to direct REST API call if needed
                logging.info("Using alternative method to create thread")
                thread_response = project_client.agents.threads.create()
                thread_id = thread_response.id
        else:
            thread_id = threadid
            
        # Create a message in the thread
        message = project_client.agents.create_message(
            thread_id=thread_id,
            role="user",
            content=message
        )

        # Process the message with the agent
        project_client.agents.create_and_process_run(
            thread_id=thread_id,
            agent_id=agent.id
        )

        # Get the messages from the thread
        messages = project_client.agents.list_messages(thread_id=thread_id)
        messages_dict = messages.as_dict()
        
        # Extract the latest assistant message
        assistant_text = ""
        assistant_messages = [m for m in messages_dict['data'] if m.get('role') == 'assistant']
        
        if assistant_messages:
            # Get the latest assistant message (first in the list since they're ordered by created_at desc)
            latest_assistant = assistant_messages[0]
            
            # Extract text from content
            content_parts = latest_assistant.get('content', [])
            text_parts = []
            for part in content_parts:
                if part.get('type') == 'text' and 'text' in part:
                    text_parts.append(part['text']['value'])
            
            assistant_text = " ".join(text_parts) if text_parts else "No text content found."
        else:
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

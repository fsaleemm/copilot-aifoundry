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
    parameters = None
    
    if not message or not agentid:
        try:
            req_body = req.get_json()
        except ValueError:
            req_body = None

        if req_body:
            message = req_body.get('message')
            agentid = req_body.get('agentid')
            threadid = req_body.get('threadid')
            parameters = req_body.get('parameters')  # JSON object with name-value pairs

    if not message or not agentid:
        return func.HttpResponse(
            json.dumps({
                "error": "Missing required parameters 'message' and 'agentid'",
                "usage": "Provide 'message' and 'agentid' in query string or request body. Optional: 'threadid', 'parameters'"
            }),
            status_code=400,
            mimetype="application/json"
        )

    # Apply message template if configured
    # MESSAGE_TEMPLATE example: "user_id: {user_id}, username: {username}, question: {message}"
    message_template = os.environ.get("MESSAGE_TEMPLATE")
    if message_template:
        template_vars = {"message": message}
        if parameters and isinstance(parameters, dict):
            template_vars.update(parameters)
        try:
            message = message_template.format(**template_vars)
            logging.info(f"Applied message template with variables: {list(template_vars.keys())}")
        except KeyError as e:
            return func.HttpResponse(
                json.dumps({
                    "error": f"Missing required parameter for message template: {str(e)}",
                    "provided_parameters": list(template_vars.keys()),
                    "template": message_template
                }),
                status_code=400,
                mimetype="application/json"
            )

    endpoint = os.environ.get("AIProjectEndpoint")
    
    if not endpoint:
        logging.error("AIProjectEndpoint must be set in environment variables.")
        return func.HttpResponse(
            "Internal Server Error: Missing AIProjectEndpoint configuration.",
            status_code=500
        )

    try:
        # Use endpoint-based authentication (SDK 2.0+)
        project_client = AIProjectClient(
            endpoint=endpoint,
            credential=DefaultAzureCredential(),
        )

        openai_client = project_client.get_openai_client()

        # agentid format: "name:version" or just "name"
        if ":" in agentid:
            agent_name, agent_version = agentid.split(":", 1)
        else:
            agent_name = agentid
            agent_version = None

        # Build agent reference
        agent_ref = {"name": agent_name, "type": "agent_reference"}
        if agent_version:
            agent_ref["version"] = agent_version

        # Create response using the OpenAI Responses API with agent reference
        create_kwargs = {
            "input": [{"role": "user", "content": message}],
            "extra_body": {"agent_reference": agent_ref},
        }
        if threadid:
            create_kwargs["previous_response_id"] = threadid

        response = openai_client.responses.create(**create_kwargs)

        # Build a map of annotations for citation replacement
        annotations_map = {}
        for item in response.output:
            if item.type == "message" and item.role == "assistant":
                for content_block in item.content:
                    if hasattr(content_block, "annotations") and content_block.annotations:
                        for ann in content_block.annotations:
                            if ann.type == "url_citation":
                                citation_text = content_block.text[ann.start_index:ann.end_index]
                                md_link = f"[{ann.title}]({ann.url})"
                                annotations_map[citation_text] = md_link

        # Replace citations in the output text
        assistant_text = response.output_text
        for citation, md_link in annotations_map.items():
            assistant_text = assistant_text.replace(citation, md_link)

        if not assistant_text:
            assistant_text = "No assistant message found."

        # Return the response with the thread ID for continuity
        response_data = {
            "message": assistant_text,
            "threadId": response.id
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

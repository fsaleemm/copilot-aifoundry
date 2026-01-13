"""
Script to list all agents in your Azure AI Foundry project and display their IDs.
Uses AIProjectClient to access New AI Foundry agents.
"""
import asyncio
import os
import json
from pathlib import Path
from azure.ai.projects.aio import AIProjectClient
from azure.identity.aio import DefaultAzureCredential


async def list_all_agents():
    """List all agents in the project using AIProjectClient."""
    # Try to load from local.settings.json first
    endpoint = os.environ.get("AIProjectEndpoint")
    
    if not endpoint:
        settings_file = Path(__file__).parent / "local.settings.json"
        if settings_file.exists():
            with open(settings_file) as f:
                settings = json.load(f)
                values = settings.get("Values", {})
                endpoint = values.get("AIProjectEndpoint")
    
    if not endpoint:
        print("Error: AIProjectEndpoint not found in environment or local.settings.json")
        return
    
    async with DefaultAzureCredential() as credential:
        async with AIProjectClient(endpoint=endpoint, credential=credential) as project_client:
            print(f"\nListing agents from: {endpoint}\n")
            print(f"{'Agent ID':<45} {'Name':<30}")
            print("-" * 80)
            
            try:
                # Use AIProjectClient.agents.list() for New Foundry
                agents_list = project_client.agents.list()
                count = 0
                
                # AsyncItemPaged requires async iteration
                async for agent in agents_list:
                    name = getattr(agent, 'name', 'N/A')
                    agent_id = getattr(agent, 'id', 'N/A')
                    print(f"{agent_id:<45} {name:<30}")
                    
                    # Show tools if available
                    if hasattr(agent, 'tools') and agent.tools:
                        print(f"  └─ Tools: {len(agent.tools)} configured")
                    
                    count += 1
                
                print(f"\nTotal agents found: {count}")
                
                if count > 0:
                    print(f"\nTo use an agent, add this to local.settings.json:")
                    print(f'  "AGENT_ID": "<agent-id-from-above>"')
                
            except Exception as e:
                print(f"Error listing agents: {e}")
                import traceback
                traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(list_all_agents())

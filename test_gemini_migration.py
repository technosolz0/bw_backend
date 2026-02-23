import asyncio
import unittest
from unittest.mock import MagicMock, patch
import os
import sys

# Add current directory to path
sys.path.append(os.getcwd())

# Mock the database and models before importing gemini service
sys.modules['app.database'] = MagicMock()
sys.modules['app.models.sql_models'] = MagicMock()

from app.services.gemini import generate_content_with_file_search, types

class TestGeminiMigration(unittest.IsolatedAsyncioTestCase):
    @patch('google.genai.Client')
    async def test_generate_content_success(self, MockClient):
        # Setup mock client
        mock_client_instance = MockClient.return_value
        mock_chat = MagicMock()
        mock_client_instance.chats.create.return_value = mock_chat
        
        # Mock response
        mock_response = MagicMock()
        mock_response.text = "Hello, how can I help you?"
        mock_content = MagicMock()
        mock_content.parts = [types.Part.from_text(text="Hello, how can I help you?")]
        mock_candidate = MagicMock()
        mock_candidate.content = mock_content
        mock_response.candidates = [mock_candidate]
        
        mock_chat.send_message.return_value = mock_response
        
        # Test call
        client_id = "test_client"
        prompt = "Hello"
        api_key = "test_key"
        store_ids = ["store_1"]
        
        result = await generate_content_with_file_search(client_id, prompt, api_key, store_ids)
        
        # Assertions
        self.assertEqual(result, "Hello, how can I help you?")
        MockClient.assert_called_once_with(api_key=api_key)
        mock_client_instance.chats.create.assert_called_once()

    @patch('google.genai.Client')
    @patch('app.services.gemini.notify_sales_team')
    async def test_generate_content_tool_call(self, mock_notify, MockClient):
        # Setup mock client
        mock_client_instance = MockClient.return_value
        mock_chat = MagicMock()
        mock_client_instance.chats.create.return_value = mock_chat
        
        # Mock tool call response
        mock_response = MagicMock()
        mock_response.text = "" # Tool call often has empty text initially or we handle it
        
        # Simulate a function call part
        mock_call = MagicMock()
        mock_call.name = "scheduleCall"
        mock_call.args = {"dateTime": "2025-12-25 10:00", "reason": "Test topic"}
        
        mock_part = MagicMock()
        mock_part.call = mock_call
        mock_part.text = None
        
        mock_content = MagicMock()
        mock_content.parts = [mock_part]
        
        mock_candidate = MagicMock()
        mock_candidate.content = mock_content
        mock_response.candidates = [mock_candidate]
        
        mock_chat.send_message.return_value = mock_response
        
        # Test call
        client_id = "test_client"
        prompt = "I want to schedule a call"
        api_key = "test_key"
        store_ids = ["store_1"]
        
        result = await generate_content_with_file_search(client_id, prompt, api_key, store_ids)
        
        # Assertions
        self.assertIn("2025-12-25 10:00", result)
        mock_notify.assert_called_once_with(client_id, None, "2025-12-25 10:00", "Test topic")

if __name__ == '__main__':
    unittest.main()

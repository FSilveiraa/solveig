"""End-to-end conversation loop tests with realistic user scenarios."""

from unittest.mock import patch
import pytest

from scripts.run import main_loop
from solveig.schema.message import LLMMessage
from solveig.schema.requirements import ReadRequirement, WriteRequirement, CommandRequirement
from tests.mocks import DEFAULT_CONFIG, MockInterface, create_mock_client


class TestRealWorldConversationScenarios:
    """Test realistic user scenarios through complete conversation loops."""

    @patch("scripts.run.llm.get_instructor_client")
    @patch("scripts.run.system_prompt.get_system_prompt")
    def test_slow_computer_diagnosis_scenario(
        self, mock_get_prompt, mock_get_client, mock_all_file_operations
    ):
        """Test: User asks for help with slow computer, LLM suggests diagnostic commands."""
        # Setup
        mock_get_prompt.return_value = "You are a helpful assistant that can run commands and read files."
        
        # LLM responds with diagnostic commands
        llm_response = LLMMessage(
            comment="I'll help diagnose your slow computer. Let me check system resources and running processes.",
            requirements=[
                CommandRequirement(
                    command="top -b -n1 | head -20",
                    comment="Check CPU and memory usage"
                ),
                CommandRequirement(
                    command="df -h",
                    comment="Check disk space usage"
                ),
                CommandRequirement(
                    command="ps aux --sort=-%cpu | head -10",
                    comment="Find processes using most CPU"
                )
            ]
        )
        
        mock_client = create_mock_client(llm_response)
        mock_get_client.return_value = mock_client
        
        interface = MockInterface()
        interface.set_user_inputs([
            "y",  # Accept top command
            "y",  # Accept df command  
            "y",  # Accept ps command
            "exit"  # End conversation
        ])
        
        # Execute realistic user request
        try:
            main_loop(DEFAULT_CONFIG, interface, "My computer is running very slow, can you help me figure out why?")
        except ValueError:
            pass
        
        # Verify appropriate diagnostic approach
        interface.assert_output_contains("help diagnose your slow computer")
        interface.assert_output_contains("Check CPU and memory usage")
        interface.assert_output_contains("Check disk space usage")
        interface.assert_output_contains("Find processes using most CPU")
        
        # Verify all commands were processed
        all_output = interface.get_all_output()
        assert "top -b -n1" in all_output
        assert "df -h" in all_output
        assert "ps aux" in all_output

    @patch("scripts.run.llm.get_instructor_client")
    @patch("scripts.run.system_prompt.get_system_prompt")
    def test_file_organization_scenario(
        self, mock_get_prompt, mock_get_client, mock_all_file_operations
    ):
        """Test: User asks to organize files in Downloads directory."""
        # Setup
        mock_get_prompt.return_value = "You are a helpful assistant that can organize files and directories."
        
        # LLM responds with file organization plan
        llm_response = LLMMessage(
            comment="I'll help organize your Downloads folder. First, let me see what files are there, then create organized folders and move files appropriately.",
            requirements=[
                ReadRequirement(
                    path="/home/francisco/Downloads",
                    metadata_only=False,
                    comment="Examine Downloads directory contents"
                ),
                WriteRequirement(
                    path="/home/francisco/Downloads/Documents",
                    content="",
                    is_directory=True,
                    comment="Create Documents folder for organizing files"
                ),
                WriteRequirement(
                    path="/home/francisco/Downloads/Images", 
                    content="",
                    is_directory=True,
                    comment="Create Images folder for photos and pictures"
                ),
                CommandRequirement(
                    command="find /home/francisco/Downloads -maxdepth 1 -name '*.pdf' -o -name '*.doc*' -o -name '*.txt'",
                    comment="Find document files to organize"
                )
            ]
        )
        
        mock_client = create_mock_client(llm_response)
        mock_get_client.return_value = mock_client
        
        interface = MockInterface()
        interface.set_user_inputs([
            "y",  # Accept reading Downloads directory
            "y",  # Accept creating Documents folder
            "y",  # Accept creating Images folder
            "y",  # Accept finding document files
            "exit"  # End conversation
        ])
        
        # Execute realistic organization request
        try:
            main_loop(DEFAULT_CONFIG, interface, "Can you help me organize all the files in my Downloads folder? It's a complete mess.")
        except ValueError:
            pass
        
        # Verify systematic organization approach
        interface.assert_output_contains("help organize your Downloads folder")
        interface.assert_output_contains("Examine Downloads directory contents")
        interface.assert_output_contains("Create Documents folder")
        interface.assert_output_contains("Create Images folder")
        interface.assert_output_contains("Find document files")
        
        # Verify proper file operations were suggested
        all_output = interface.get_all_output()
        assert "/home/francisco/Downloads" in all_output
        assert "Documents" in all_output
        assert "Images" in all_output

    @patch("scripts.run.llm.get_instructor_client")
    @patch("scripts.run.system_prompt.get_system_prompt") 
    def test_suspicious_script_analysis_scenario(
        self, mock_get_prompt, mock_get_client, mock_all_file_operations
    ):
        """Test: User asks what a suspicious script does - security-focused analysis."""
        # Setup
        mock_get_prompt.return_value = "You are a security-focused assistant that can analyze files safely."
        
        # LLM responds with careful security analysis approach
        llm_response = LLMMessage(
            comment="I'll analyze this script safely without executing it. Let me examine its contents, check file permissions, and look for any suspicious patterns.",
            requirements=[
                ReadRequirement(
                    path="/home/francisco/suspicious_script.sh",
                    metadata_only=True,
                    comment="Check script file permissions and metadata first"
                ),
                ReadRequirement(
                    path="/home/francisco/suspicious_script.sh", 
                    metadata_only=False,
                    comment="Read script contents for analysis"
                ),
                CommandRequirement(
                    command="file /home/francisco/suspicious_script.sh",
                    comment="Determine file type and characteristics"
                ),
                CommandRequirement(
                    command="strings /home/francisco/suspicious_script.sh | head -20",
                    comment="Extract readable strings to identify potential threats"
                )
            ]
        )
        
        mock_client = create_mock_client(llm_response)
        mock_get_client.return_value = mock_client
        
        interface = MockInterface()
        interface.set_user_inputs([
            "y",  # Accept checking metadata
            "y",  # Accept reading contents
            "y",  # Accept file command
            "y",  # Accept strings analysis
            "exit"  # End conversation
        ])
        
        # Execute security analysis request
        try:
            main_loop(DEFAULT_CONFIG, interface, "I found this script called 'suspicious_script.sh' on my computer. Can you tell me what it does? I'm worried it might be malware.")
        except ValueError:
            pass
        
        # Verify security-conscious analysis approach
        interface.assert_output_contains("analyze this script safely")
        interface.assert_output_contains("without executing it")
        interface.assert_output_contains("Check script file permissions")
        interface.assert_output_contains("Read script contents for analysis")
        interface.assert_output_contains("Determine file type")
        interface.assert_output_contains("identify potential threats")
        
        # Verify safe analysis methods were used
        all_output = interface.get_all_output()
        assert "suspicious_script.sh" in all_output
        assert "file " in all_output  # file command for type detection
        assert "strings " in all_output  # strings command for analysis
        # Importantly, no direct execution of the suspicious script
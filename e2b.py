from core.tools.errors import ToolProviderCredentialValidationError
from core.tools.provider.builtin_tool_provider import BuiltinToolProviderController
from core.tools.provider.builtin.e2b.tools.e2b_sandbox import E2BSandboxTool
import os

class E2BProvider(BuiltinToolProviderController):
    def _validate_credentials(self, credentials: dict) -> None:
        try:
            # Set the API key in the environment variable
            os.environ['E2B_API_KEY'] = credentials['e2b_api_key']

            E2BSandboxTool().fork_tool_runtime(
                runtime={
                    "credentials": credentials,
                }
            ).invoke(
                user_id="",
                tool_parameters={
                    "code": "print('test')",
                    "language": "python",
                },
            )
        except Exception as e:
            raise ToolProviderCredentialValidationError(f"Invalid credentials: {str(e)}")

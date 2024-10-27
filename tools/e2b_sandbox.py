from core.tools.tool.builtin_tool import BuiltinTool
from core.tools.entities.tool_entities import ToolInvokeMessage
from typing import Any, Dict, List, Union, ClassVar, Set
from e2b_code_interpreter import Sandbox
import os
import base64
from dataclasses import dataclass, field

@dataclass
class E2BSandboxTool(BuiltinTool):
    # Class attribute definition
    variable_pool: Dict[str, Any] = field(default_factory=dict)
    
    # Adding variable key definitions
    class VARIABLE_KEY:
        class TEXT:
            value = 'text'
    
    VARIABLE_KEY_IMAGES: ClassVar[str] = 'images'

    def __init__(self, identity: dict = None, **kwargs):
        super().__init__(identity=identity, **kwargs)
        # variable_pool will be automatically initialized by dataclass

    def _is_image_file(self, filename: str) -> bool:
        """Check if the file is an image"""
        image_extensions = {'.png', '.jpg', '.jpeg', '.svg', '.gif', '.bmp'}
        return os.path.splitext(filename.lower())[1] in image_extensions

    def _get_mime_type(self, filename: str) -> str:
        """Get the MIME type of the file"""
        ext = os.path.splitext(filename)[1].lower()
        mime_types = {
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.svg': 'image/svg+xml',
            '.gif': 'image/gif',
            '.bmp': 'image/bmp'
        }
        return mime_types.get(ext, 'application/octet-stream')

    def _list_files_recursive(self, sbx: Sandbox, path: str = '/') -> Set[str]:
        """Recursively get all file paths"""
        all_files = set()
        try:
            items = sbx.filesystem.list(path)
            for item in items:
                full_path = os.path.join(path, item).replace('\\', '/')
                all_files.add(full_path)
                try:
                    # Attempt to list contents as a directory
                    sub_items = sbx.filesystem.list(full_path)
                    all_files.update(self._list_files_recursive(sbx, full_path))
                except:
                    # If failed, it means it's a file, continue to the next one
                    continue
        except Exception as e:
            print(f"Error listing directory {path}: {str(e)}")
        return all_files

    def _process_image_file(self, sbx: Sandbox, filepath: str) -> Dict[str, Any]:
        """Process a single image file"""
        try:
            content = sbx.filesystem.read(filepath)
            mime_type = self._get_mime_type(filepath)
            filename = os.path.basename(filepath)
            
            return {
                'filename': filename,
                'content': content,
                'mime_type': mime_type
            }
        except Exception as e:
            print(f"Error processing file {filepath}: {str(e)}")
            return None

    def _preprocess_matplotlib_code(self, code: str) -> str:
        """Preprocess code containing matplotlib, ensuring images are displayed"""
        if 'plt.savefig' in code and 'plt.show()' not in code:
            # Split code lines
            lines = code.split('\n')
            processed_lines = []
            
            for line in lines:
                processed_lines.append(line)
                # Add show after each savefig
                if 'plt.savefig' in line and not line.strip().startswith('#'):
                    # Keep the same indentation as the original code
                    indent = len(line) - len(line.lstrip())
                    processed_lines.append(' ' * indent + 'plt.show()')
            
            return '\n'.join(processed_lines)
        return code

    def _invoke(self, user_id: str, tool_parameters: Dict[str, Any]) \
            -> Union[ToolInvokeMessage, List[ToolInvokeMessage]]:
        code = tool_parameters['code']
        language = tool_parameters.get('language', 'python')
        template_id = tool_parameters.get('template_id', None)
        timeout = tool_parameters.get('timeout', 300)
        api_key = self.runtime.credentials['e2b_api_key']

        # Preprocess code
        if language.lower() == 'python':
            code = self._preprocess_matplotlib_code(code)

        # Set environment variables
        os.environ['E2B_API_KEY'] = api_key

        output_messages = []
        images_list = []

        # Create Sandbox
        try:
            if template_id:
                sbx = Sandbox(timeout=timeout, template_id=template_id)
            else:
                sbx = Sandbox(timeout=timeout)
        except Exception as e:
            return self.create_text_message(text=f"Error creating sandbox session: {str(e)}")

        try:
            # Get initial file list
            initial_files = self._list_files_recursive(sbx)
            
            # Execute code
            execution = sbx.run_code(code, language=language)
            
            # Get file list after execution
            final_files = self._list_files_recursive(sbx)
            
            # Find new files generated
            new_files = final_files - initial_files
            
            # Process new image files generated
            for file in new_files:
                if self._is_image_file(file):
                    image_data = self._process_image_file(sbx, file)
                    if image_data:
                        output_messages.append(self.create_blob_message(
                            blob=image_data['content'],
                            meta={'mime_type': image_data['mime_type']},
                            save_as=''
                        ))
                        images_list.append(image_data)

            # Process execution results
            if execution.error:
                error_message = f"Error in code execution:\n{execution.error.name}: {execution.error.value}\n{execution.error.traceback}"
                output_messages.append(self.create_text_message(text=error_message))
            else:
                # Process standard output
                stdout = execution.logs
                if stdout:
                    output_messages.append(self.create_text_message(
                        text=f"Output:\n{stdout}",
                        save_as=self.VARIABLE_KEY.TEXT.value
                    ))

                # Process images and text in execution results
                for result in execution.results:
                    if result.png:
                        image_content = base64.b64decode(result.png)
                        output_messages.append(self.create_blob_message(
                            blob=image_content,
                            meta={'mime_type': 'image/png'},
                            save_as=''
                        ))
                        images_list.append({
                            'filename': 'image.png',
                            'content': image_content,
                            'mime_type': 'image/png'
                        })
                    elif result.jpeg:
                        image_content = base64.b64decode(result.jpeg)
                        output_messages.append(self.create_blob_message(
                            blob=image_content,
                            meta={'mime_type': 'image/jpeg'},
                            save_as=''
                        ))
                        images_list.append({
                            'filename': 'image.jpeg',
                            'content': image_content,
                            'mime_type': 'image/jpeg'
                        })
                    elif result.text:
                        output_messages.append(self.create_text_message(
                            text=result.text,
                            save_as=self.VARIABLE_KEY.TEXT.value
                        ))

            # Save image list to variable pool
            if images_list:
                self.variable_pool[self.VARIABLE_KEY_IMAGES] = images_list

        except Exception as e:
            sbx.kill()
            return self.create_text_message(text=f"Error executing code: {str(e)}")


        return output_messages if output_messages else self.create_text_message(text="No output returned.")
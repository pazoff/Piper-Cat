import os
from cat.mad_hatter.decorators import hook, plugin
from cat.log import log
from pydantic import BaseModel
from enum import Enum
import subprocess
from datetime import datetime
from threading import Thread
import re
from gtts import gTTS
from langdetect import detect
from langdetect.lang_detect_exception import LangDetectException
import shlex
import json

# Settings

# Select box
class VoiceSelect(Enum):
    Alice: str = 'Alice'
    Eve: str = 'Eve'
    Amy: str = 'Amy'
    Sonya: str = 'Sonya'
    Stephany: str = 'Stephany'
    Dave: str = 'Dave'
    Stephan: str = 'Stephan'
    Joe: str = 'Joe'
    Ruslan: str = 'Ruslan'
    Riccardo: str = 'Riccardo'
    Paola: str = 'Paola'


def check_and_update_voices():
    file_path = '/app/voices.json'
    if not os.path.exists(file_path):
        try:
            # Run the command
            result = subprocess.run(
                ["piper", "--update-voices", "-m", "en_US-ryan-high"],
                check=True,  # This will raise a CalledProcessError if the command fails
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            # Decode output with error handling
            stdout = result.stdout.decode('utf-8', errors='replace')
            stderr = result.stderr.decode('utf-8', errors='replace')
            #print("Command output:", stdout)
            log.warning("Voices update completed successfully")
        except subprocess.CalledProcessError as e:
            stderr = e.stderr.decode('utf-8', errors='replace')
            log.error(f"An error occurred while updating voices: {stderr}")
        except Exception as e:
            log.error(f"An unexpected error occurred: {e}")

def get_voices():
    check_and_update_voices()
    with open("/app/voices.json") as F:
        voices = json.load(F)
    return { f"{v['name'].capitalize()} ({v['language']['name_native']})" : (v['key'], None) for v in voices.values() }

VoiceSelect = Enum("VoiceSelect", { k:k for k in get_voices() })

class piperCatSettings(BaseModel):
    # Select
    Voice: VoiceSelect = list(VoiceSelect)[0]
    use_gTTS: bool = False

# Give your settings schema to the Cat.
@plugin
def settings_schema():
    return piperCatSettings.schema()

def has_cyrillic(text):
    # Regular expression to match Cyrillic characters
    cyrillic_pattern = re.compile('[\u0400-\u04FF]+')
    
    # Check if any Cyrillic character is present in the text
    return bool(cyrillic_pattern.search(text))

def remove_special_characters(text):
    # Define the pattern to match special characters excluding punctuation, single and double quotation marks, and Cyrillic characters
    pattern = r'[^a-zA-Z0-9\s.,!?\'"а-яА-Я]'  # Matches any character that is not alphanumeric, whitespace, or specific punctuation, including Cyrillic characters
    pattern = r'[^a-zA-Z0-9À-ÖØ-öø-ÿ\s.,!?\'"а-яА-Я]'  # Matches any character that is not alphanumeric, whitespace, or specific punctuation, including Cyrillic characters
    
    # Replace special characters with an empty string
    clean_text = re.sub(pattern, '', text)
    
    return clean_text


def run_gtts_process(text, filename, cat):
    try:
        language = detect(text)
    except LangDetectException:
        print("Error: Language detection failed. Defaulting to English.")
        language = 'en'
    
    try:
        tts = gTTS(text=text, lang=language, slow=False)
        tts.save(filename)

        # Generate the audio player HTML and send it as a chat message
        gtts_audio_player = "<audio controls autoplay><source src='" + filename + "' type='audio/mp3'>Your browser does not support the audio element.</audio>"
        cat.send_ws_message(content=gtts_audio_player, msg_type='chat')

    except Exception as e:
        print(f"Error occurred: {str(e)}")
        #logging.error(f"Error occurred: {str(e)}")

# Function to run piper process in the background
def run_piper_process(command, output_filename, cat):

    check_and_update_voices()
    
    command_string = " ".join(command)
    command_string = command_string + output_filename
    
    # Execute the command
    try:
        subprocess.run(command_string, shell=True, check=True)
    except subprocess.CalledProcessError as e:
        log.error(f"Error during command execution: {e}")
        log.error(f"Error output: {e.stderr.decode()}")
        return

    # Generate the audio player HTML and send it as a chat message
    piper_audio_player = f"<audio controls autoplay><source src='{output_filename}' type='audio/wav'>Your browser does not support the audio tag.</audio><a href='{output_filename}' target='_blank'>Download Audio</a>"
    cat.send_ws_message(content=piper_audio_player, msg_type='chat')


# Build piper command based on selected voice
def build_piper_command(llm_message: str, cat):

    cleaned_text = remove_special_characters(llm_message)
    piper_cmd = [f"echo {shlex.quote(cleaned_text)} | ", "piper"]

    # Load the settings
    settings = cat.mad_hatter.get_plugin().load_settings()
    selected_voice = settings.get("Voice")

    # Check if selected_voice is None or not in the specified list
    #if selected_voice not in ["Alice", "Dave", "Ruslan", "Eve", "Amy", "Stephany", "Stephan", "Joe", "Sonya", "Riccardo", "Valeria", "Paola"]:
    #    selected_voice = "Paola"
    
    if has_cyrillic(llm_message):
        selected_voice = "Ruslan"

    # Voice mapping dictionary
    voice_mapping = {
        "Alice": ("en_US-lessac-high", None),
        "Dave": ("en_US-ryan-high", None),
        "Ruslan": ("ru_RU-ruslan-medium", None),
        "Eve": ("en_GB-vctk-medium", "99"),
        "Amy": ("en_US-amy-medium", None),
        "Stephany": ("en_US-hfc_female-medium", None),
        "Stephan": ("en_US-hfc_male-medium", None),
        "Joe": ("en_US-joe-medium", None),
        "Sonya": ("en_US-ljspeech-medium", None),
        "Riccardo": ("it_IT-riccardo-x_low", None),
        "Paola": ("it_IT-paola-medium", None),
    }
    voice_mapping = get_voices()

    # Set default values if selected_voice is not in the mapping
    voice_cmd, speaker_cmd = voice_mapping.get(selected_voice, ("en_US-ryan-high", None))

    piper_cmd.extend(["--model", voice_cmd])

    # Add speaker command if available
    if speaker_cmd is not None:
        piper_cmd.extend(["-s", speaker_cmd])

    piper_cmd.append("--output_file ")

    return piper_cmd


# Hook function that runs before sending a message
@hook
def before_cat_sends_message(final_output, cat):
    # Get the current date and time
    current_datetime = datetime.now()
    # Format the date and time to use as part of the filename
    formatted_datetime = current_datetime.strftime("%Y%m%d_%H%M%S")
    # Specify the folder path
    folder_path = "/admin/assets/voice"

    # Check if the folder exists, create it if not
    if not os.path.exists(folder_path):
        os.makedirs(folder_path)

    # Construct the output file name with the formatted date and time
    output_filename = os.path.join(folder_path, f"voice_{formatted_datetime}.wav")

    # Get the message sent by LLM
    message = final_output.content

    # Load the settings
    settings = cat.mad_hatter.get_plugin().load_settings()
    use_gtts = settings.get("use_gTTS")
    if use_gtts is None:
        use_gtts = False

    if use_gtts:
        gtts_tread = Thread(target=run_gtts_process, args=(message, output_filename, cat))
        gtts_tread.start()

    else:
        # Specify the piper command
        command = build_piper_command(message, cat)

        # Run the run_piper_process function in a separate thread
        piper_thread = Thread(target=run_piper_process, args=(command, output_filename, cat))
        piper_thread.start()

    # Return the final output text, leaving piper to build the audio file in the background
    return final_output

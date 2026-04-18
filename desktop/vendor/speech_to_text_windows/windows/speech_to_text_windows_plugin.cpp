#include "speech_to_text_windows_plugin.h"

#include <flutter/method_channel.h>
#include <flutter/plugin_registrar_windows.h>
#include <flutter/standard_method_codec.h>

#include <windows.h>
#include <sapi.h>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>

namespace speech_to_text_windows {

namespace {

constexpr UINT_PTR kRecognitionPollTimerId = 0x4F534352;

std::string EscapeJson(const std::string& input) {
  std::ostringstream escaped;
  for (const unsigned char ch : input) {
    switch (ch) {
      case '\\':
        escaped << "\\\\";
        break;
      case '"':
        escaped << "\\\"";
        break;
      case '\b':
        escaped << "\\b";
        break;
      case '\f':
        escaped << "\\f";
        break;
      case '\n':
        escaped << "\\n";
        break;
      case '\r':
        escaped << "\\r";
        break;
      case '\t':
        escaped << "\\t";
        break;
      default:
        if (ch < 0x20) {
          escaped << "\\u" << std::hex << std::setw(4) << std::setfill('0')
                  << static_cast<int>(ch) << std::dec;
        } else {
          escaped << ch;
        }
        break;
    }
  }
  return escaped.str();
}

std::string BuildRecognitionJson(const std::string& text, bool is_final) {
  return "{\"alternates\":[{\"recognizedWords\":\"" + EscapeJson(text) +
         "\",\"recognizedPhrases\":null,\"confidence\":-1.0}],\"finalResult\":" +
         std::string(is_final ? "true" : "false") + "}";
}

std::string BuildErrorJson(const std::string& error, bool permanent) {
  return "{\"errorMsg\":\"" + EscapeJson(error) + "\",\"permanent\":" +
         std::string(permanent ? "true" : "false") + "}";
}

}  // namespace

void SpeechToTextWindowsPlugin::RegisterWithRegistrar(
    flutter::PluginRegistrarWindows *registrar) {
  auto plugin = std::make_unique<SpeechToTextWindowsPlugin>();
  plugin->m_registrar = registrar;
  if (auto* view = registrar->GetView()) {
    plugin->m_window_handle = view->GetNativeWindow();
  }

  plugin->m_channel =
      std::make_unique<flutter::MethodChannel<flutter::EncodableValue>>(
          registrar->messenger(), "speech_to_text_windows",
          &flutter::StandardMethodCodec::GetInstance());

  plugin->m_channel->SetMethodCallHandler(
      [plugin_pointer = plugin.get()](const auto &call, auto result) {
        plugin_pointer->HandleMethodCall(call, std::move(result));
      });

  plugin->m_window_proc_delegate_id =
      registrar->RegisterTopLevelWindowProcDelegate(
          [plugin_pointer = plugin.get()](HWND hwnd, UINT message, WPARAM wparam,
                                          LPARAM lparam)
              -> std::optional<LRESULT> {
            return plugin_pointer->HandleWindowProc(hwnd, message, wparam,
                                                    lparam);
          });

  registrar->AddPlugin(std::move(plugin));
}

SpeechToTextWindowsPlugin::SpeechToTextWindowsPlugin() 
  : m_cpRecognizer(nullptr)
  , m_cpRecoContext(nullptr)
  , m_cpRecoGrammar(nullptr)
  , m_cpAudio(nullptr)
  , m_initialized(false)
  , m_listening(false) {
  std::cout << "SpeechToTextWindowsPlugin created" << std::endl;
  CoInitializeEx(NULL, COINIT_APARTMENTTHREADED);
}

SpeechToTextWindowsPlugin::~SpeechToTextWindowsPlugin() {
  std::cout << "SpeechToTextWindowsPlugin destroyed" << std::endl;

  if (m_registrar != nullptr && m_window_proc_delegate_id != 0) {
    m_registrar->UnregisterTopLevelWindowProcDelegate(m_window_proc_delegate_id);
    m_window_proc_delegate_id = 0;
  }

  if (m_window_handle != nullptr) {
    KillTimer(m_window_handle, kRecognitionPollTimerId);
  }

  if (m_listening && m_cpRecoGrammar) {
    m_cpRecoGrammar->SetDictationState(SPRS_INACTIVE);
    m_listening = false;
  }

  if (m_cpRecoGrammar) {
    m_cpRecoGrammar->Release();
    m_cpRecoGrammar = nullptr;
  }
  if (m_cpRecoContext) {
    m_cpRecoContext->Release();
    m_cpRecoContext = nullptr;
  }
  if (m_cpRecognizer) {
    m_cpRecognizer->Release();
    m_cpRecognizer = nullptr;
  }
  if (m_cpAudio) {
    m_cpAudio->Release();
    m_cpAudio = nullptr;
  }
  
  CoUninitialize();
}

void SpeechToTextWindowsPlugin::HandleMethodCall(
    const flutter::MethodCall<flutter::EncodableValue> &method_call,
    std::unique_ptr<flutter::MethodResult<flutter::EncodableValue>> result) {
  
  const std::string& method_name = method_call.method_name();
  std::cout << "Method called: " << method_name << std::endl;
  
  if (method_name == "hasPermission") {
    result->Success(flutter::EncodableValue(true));
  } else if (method_name == "initialize") {
    Initialize(method_call, std::move(result));
  } else if (method_name == "listen") {
    Listen(method_call, std::move(result));
  } else if (method_name == "stop") {
    Stop(std::move(result));
  } else if (method_name == "cancel") {
    Cancel(std::move(result));
  } else if (method_name == "locales") {
    GetLocales(std::move(result));
  } else {
    result->NotImplemented();
  }
}

void SpeechToTextWindowsPlugin::Initialize(
    const flutter::MethodCall<flutter::EncodableValue> &method_call,
    std::unique_ptr<flutter::MethodResult<flutter::EncodableValue>> result) {
  
  std::lock_guard<std::mutex> lock(m_mutex);
  
  if (m_initialized) {
    std::cout << "Already initialized" << std::endl;
    result->Success(flutter::EncodableValue(true));
    return;
  }

  std::cout << "Initializing SAPI speech recognition..." << std::endl;

  try {
    HRESULT hr = S_OK;

    // Create a recognition engine
    hr = CoCreateInstance(CLSID_SpInprocRecognizer, NULL, CLSCTX_INPROC_SERVER, 
                         IID_ISpRecognizer, (void**)&m_cpRecognizer);
    if (FAILED(hr)) {
      std::cout << "Failed to create speech recognizer. HRESULT: " << std::hex << hr << std::endl;
      result->Success(flutter::EncodableValue(false));
      return;
    }

    // Create default audio input
    hr = CoCreateInstance(CLSID_SpMMAudioIn, NULL, CLSCTX_INPROC_SERVER,
                         IID_ISpAudio, (void**)&m_cpAudio);
    if (FAILED(hr)) {
      std::cout << "Failed to create audio input. HRESULT: " << std::hex << hr << std::endl;
      result->Success(flutter::EncodableValue(false));
      return;
    }

    // Set the audio input to our recognizer
    hr = m_cpRecognizer->SetInput(m_cpAudio, TRUE);
    if (FAILED(hr)) {
      std::cout << "Failed to set audio input. HRESULT: " << std::hex << hr << std::endl;
      result->Success(flutter::EncodableValue(false));
      return;
    }

    // Create a recognition context
    hr = m_cpRecognizer->CreateRecoContext(&m_cpRecoContext);
    if (FAILED(hr)) {
      std::cout << "Failed to create recognition context. HRESULT: " << std::hex << hr << std::endl;
      result->Success(flutter::EncodableValue(false));
      return;
    }

    // Create a grammar
    hr = m_cpRecoContext->CreateGrammar(0, &m_cpRecoGrammar);
    if (FAILED(hr)) {
      std::cout << "Failed to create grammar. HRESULT: " << std::hex << hr << std::endl;
      result->Success(flutter::EncodableValue(false));
      return;
    }

    // Enable dictation grammar
    hr = m_cpRecoGrammar->LoadDictation(NULL, SPLO_STATIC);
    if (FAILED(hr)) {
      std::cout << "Failed to load dictation grammar. HRESULT: " << std::hex << hr << std::endl;
      result->Success(flutter::EncodableValue(false));
      return;
    }

    m_initialized = true;
    std::cout << "SAPI speech recognition initialized successfully!" << std::endl;
    result->Success(flutter::EncodableValue(true));

  } catch (...) {
    std::cout << "Exception during initialization" << std::endl;
    result->Success(flutter::EncodableValue(false));
  }
}

void SpeechToTextWindowsPlugin::Listen(
    const flutter::MethodCall<flutter::EncodableValue> &method_call,
    std::unique_ptr<flutter::MethodResult<flutter::EncodableValue>> result) {
  
  std::lock_guard<std::mutex> lock(m_mutex);
  
  if (!m_initialized || !m_cpRecoGrammar) {
    std::cout << "Speech recognition not initialized" << std::endl;
    result->Error("NOT_INITIALIZED", "Speech recognition not initialized");
    return;
  }

  if (m_listening) {
    std::cout << "Already listening" << std::endl;
    result->Success(flutter::EncodableValue(true));
    return;
  }
  if (m_window_handle == nullptr) {
    std::cout << "No Flutter window handle available for speech polling" << std::endl;
    SendError("No Flutter window handle available for speech polling");
    result->Success(flutter::EncodableValue(false));
    return;
  }

  std::cout << "Starting speech recognition..." << std::endl;

  try {
    // Activate the grammar
    HRESULT hr = m_cpRecoGrammar->SetDictationState(SPRS_ACTIVE);
    if (FAILED(hr)) {
      std::cout << "Failed to activate dictation. HRESULT: " << std::hex << hr << std::endl;
      result->Success(flutter::EncodableValue(false));
      return;
    }

    m_listening = true;
    SetTimer(m_window_handle, kRecognitionPollTimerId, 50, nullptr);
    SendStatus("listening");
    std::cout << "Speech recognition listening started!" << std::endl;
    result->Success(flutter::EncodableValue(true));

  } catch (...) {
    std::cout << "Exception during listen" << std::endl;
    result->Success(flutter::EncodableValue(false));
  }
}

void SpeechToTextWindowsPlugin::Stop(
    std::unique_ptr<flutter::MethodResult<flutter::EncodableValue>> result) {
  
  std::lock_guard<std::mutex> lock(m_mutex);
  
  if (m_listening && m_cpRecoGrammar) {
    std::cout << "Stopping speech recognition..." << std::endl;
    if (m_window_handle != nullptr) {
      KillTimer(m_window_handle, kRecognitionPollTimerId);
    }
    m_cpRecoGrammar->SetDictationState(SPRS_INACTIVE);
    m_listening = false;
    SendStatus("notListening");
    std::cout << "Speech recognition stopped" << std::endl;
  }
  
  if (result) {
    result->Success(flutter::EncodableValue(nullptr));
  }
}

void SpeechToTextWindowsPlugin::Cancel(
    std::unique_ptr<flutter::MethodResult<flutter::EncodableValue>> result) {
  std::cout << "Canceling speech recognition..." << std::endl;
  Stop(std::move(result));
}

void SpeechToTextWindowsPlugin::GetLocales(
    std::unique_ptr<flutter::MethodResult<flutter::EncodableValue>> result) {
  
  flutter::EncodableList locales;
  locales.push_back(flutter::EncodableValue("en-US:English (United States)"));
  locales.push_back(flutter::EncodableValue("en-GB:English (United Kingdom)"));
  
  result->Success(flutter::EncodableValue(locales));
}

std::optional<LRESULT> SpeechToTextWindowsPlugin::HandleWindowProc(
    HWND hwnd,
    UINT message,
    WPARAM wparam,
    LPARAM lparam) {
  if (hwnd != m_window_handle) {
    return std::nullopt;
  }
  if (message == WM_TIMER && wparam == kRecognitionPollTimerId) {
    PollRecognitionEvents();
    return 0;
  }
  return std::nullopt;
}

void SpeechToTextWindowsPlugin::PollRecognitionEvents() {
  std::lock_guard<std::mutex> lock(m_mutex);

  if (!m_listening || m_cpRecoContext == nullptr) {
    return;
  }

  SPEVENT event;
  ULONG fetched = 0;

  while (m_listening) {
    HRESULT hr = m_cpRecoContext->GetEvents(1, &event, &fetched);
    if (FAILED(hr) || fetched == 0) {
      break;
    }

    std::cout << "Speech event received. Event ID: " << event.eEventId
              << std::endl;

    switch (event.eEventId) {
      case SPEI_RECOGNITION:
      case SPEI_HYPOTHESIS: {
        const bool is_final = event.eEventId == SPEI_RECOGNITION;
        std::cout << (is_final ? "SPEI_RECOGNITION event"
                               : "SPEI_HYPOTHESIS event")
                  << std::endl;
        ISpRecoResult* pResult =
            reinterpret_cast<ISpRecoResult*>(event.lParam);
        if (pResult) {
          LPWSTR pwszText;
          hr = pResult->GetText(SP_GETWHOLEPHRASE, SP_GETWHOLEPHRASE, TRUE,
                                &pwszText, NULL);
          if (SUCCEEDED(hr) && pwszText) {
            int size = WideCharToMultiByte(CP_UTF8, 0, pwszText, -1, nullptr,
                                           0, nullptr, nullptr);
            if (size > 0) {
              std::string utf8Text(size - 1, '\0');
              WideCharToMultiByte(CP_UTF8, 0, pwszText, -1, &utf8Text[0], size,
                                  nullptr, nullptr);

              std::cout << (is_final ? "Recognized text: " : "Hypothesis text: ")
                        << utf8Text << std::endl;
              SendTextRecognition(utf8Text, is_final);
            }
            CoTaskMemFree(pwszText);
          }
          pResult->Release();
        }
        break;
      }
      case SPEI_SOUND_START:
        std::cout << "Sound detected!" << std::endl;
        SendStatus("soundDetected");
        break;
      case SPEI_SOUND_END:
        std::cout << "Sound ended" << std::endl;
        SendStatus("soundEnded");
        break;
    }
  }
}

void SpeechToTextWindowsPlugin::SendTextRecognition(const std::string& text, bool is_final) {
  if (m_channel) {
    std::string json_result = BuildRecognitionJson(text, is_final);
    std::cout << "Sending to Flutter: " << json_result << std::endl;
    m_channel->InvokeMethod("textRecognition", 
        std::make_unique<flutter::EncodableValue>(json_result));
  }
}

void SpeechToTextWindowsPlugin::SendError(const std::string& error) {
  if (m_channel) {
    const std::string error_json = BuildErrorJson(error, true);
    std::cout << "Sending error: " << error_json << std::endl;
    m_channel->InvokeMethod("notifyError", 
        std::make_unique<flutter::EncodableValue>(error_json));
  }
}

void SpeechToTextWindowsPlugin::SendStatus(const std::string& status) {
  if (m_channel) {
    std::cout << "Sending status: " << status << std::endl;
    m_channel->InvokeMethod("notifyStatus", 
        std::make_unique<flutter::EncodableValue>(status));
  }
}

}  // namespace speech_to_text_windows

// C API export for Flutter plugin registration  
extern "C" __declspec(dllexport) void SpeechToTextWindowsPluginRegisterWithRegistrar(
    FlutterDesktopPluginRegistrarRef registrar) {
  speech_to_text_windows::SpeechToTextWindowsPlugin::RegisterWithRegistrar(
      flutter::PluginRegistrarManager::GetInstance()
          ->GetRegistrar<flutter::PluginRegistrarWindows>(registrar));
}

import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:speech_to_text/speech_recognition_error.dart';
import 'package:speech_to_text/speech_recognition_result.dart';
import 'package:speech_to_text/speech_to_text.dart' as stt;

void main() {
  runApp(const OscarDesktopApp());
}

class OscarDesktopApp extends StatelessWidget {
  const OscarDesktopApp({super.key});

  @override
  Widget build(BuildContext context) {
    const background = Color(0xFF101113);
    const panel = Color(0xFF181A1F);
    const accent = Color(0xFF29D3A6);

    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: 'O.S.C.A.R.',
      theme: ThemeData(
        brightness: Brightness.dark,
        scaffoldBackgroundColor: background,
        colorScheme: ColorScheme.fromSeed(
          seedColor: accent,
          brightness: Brightness.dark,
          surface: panel,
        ),
        useMaterial3: true,
        inputDecorationTheme: InputDecorationTheme(
          filled: true,
          fillColor: const Color(0xFF20232A),
          border: OutlineInputBorder(
            borderRadius: BorderRadius.circular(8),
            borderSide: const BorderSide(color: Color(0xFF343842)),
          ),
          enabledBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(8),
            borderSide: const BorderSide(color: Color(0xFF343842)),
          ),
          focusedBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(8),
            borderSide: const BorderSide(color: accent, width: 1.4),
          ),
        ),
      ),
      home: const OscarConsolePage(),
    );
  }
}

enum SocketStatus { connecting, connected, disconnected }

class OscarConsolePage extends StatefulWidget {
  const OscarConsolePage({super.key});

  @override
  State<OscarConsolePage> createState() => _OscarConsolePageState();
}

class _OscarConsolePageState extends State<OscarConsolePage> {
  static final Uri _endpoint = Uri.parse(
    String.fromEnvironment(
      'OSCAR_WS_URL',
      defaultValue: 'ws://localhost:4444/ws/oscar',
    ),
  );

  final TextEditingController _taskController = TextEditingController();
  final ScrollController _scrollController = ScrollController();
  final List<OscarFeedEvent> _events = <OscarFeedEvent>[];
  final stt.SpeechToText _speech = stt.SpeechToText();

  WebSocket? _socket;
  StreamSubscription<dynamic>? _socketSubscription;
  Timer? _reconnectTimer;
  SocketStatus _socketStatus = SocketStatus.connecting;
  bool _isConnecting = false;
  bool _isRunning = false;
  bool _speechReady = false;
  bool _isListening = false;
  bool _queuedVoiceSubmit = false;
  String _voiceFeedback = 'Initializing voice input...';

  @override
  void initState() {
    super.initState();
    _connect();
    _initSpeech();
  }

  @override
  void dispose() {
    _reconnectTimer?.cancel();
    _socketSubscription?.cancel();
    _socket?.close();
    _speech.cancel();
    _taskController.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  Future<void> _initSpeech({bool announceFailure = false}) async {
    bool ready = false;

    try {
      ready = await _speech.initialize(
        onStatus: _handleSpeechStatus,
        onError: _handleSpeechError,
        debugLogging: false,
      );
    } catch (error) {
      if (!mounted) {
        return;
      }
      setState(() {
        _speechReady = false;
        _isListening = false;
        _queuedVoiceSubmit = false;
        _voiceFeedback = 'Voice input failed to initialize.';
      });
      if (announceFailure) {
        _appendEvent(
          OscarFeedEvent.system('Voice input failed to initialize: $error', isError: true),
        );
      }
      return;
    }

    if (!mounted) {
      return;
    }

    setState(() {
      _speechReady = ready;
      _isListening = false;
      _voiceFeedback = ready
          ? 'Voice ready. Tap the mic and speak a short command.'
          : 'Voice input is unavailable on this machine.';
    });

    if (!ready && announceFailure) {
      _appendEvent(
        OscarFeedEvent.system(
          'Voice input is unavailable on this machine.',
          isError: true,
        ),
      );
    }
  }

  Future<void> _connect() async {
    if (_isConnecting || _socket?.readyState == WebSocket.open) {
      return;
    }

    _isConnecting = true;
    _setSocketStatus(SocketStatus.connecting);

    try {
      final socket = await WebSocket.connect(_endpoint.toString());
      socket.pingInterval = const Duration(seconds: 20);
      _socket = socket;
      _setSocketStatus(SocketStatus.connected);
      _appendEvent(OscarFeedEvent.system('Connected to ${_endpoint.toString()}'));

      _socketSubscription = socket.listen(
        _handleMessage,
        onDone: () => _handleDisconnect('Connection closed.'),
        onError: (Object error) => _handleDisconnect('Connection error: $error'),
        cancelOnError: true,
      );
    } catch (error) {
      _appendEvent(OscarFeedEvent.system('Unable to connect: $error', isError: true));
      _handleDisconnect('Unable to connect.');
    } finally {
      _isConnecting = false;
    }
  }

  void _handleDisconnect(String message) {
    _socketSubscription?.cancel();
    _socketSubscription = null;
    _socket = null;
    if (!mounted) {
      return;
    }
    setState(() {
      _socketStatus = SocketStatus.disconnected;
      _isRunning = false;
    });
    _appendEvent(OscarFeedEvent.system(message, isError: true));
    _reconnectTimer?.cancel();
    _reconnectTimer = Timer(const Duration(seconds: 2), _connect);
  }

  void _handleSpeechStatus(String status) {
    if (!mounted) {
      return;
    }

    final normalized = status.trim().toLowerCase();
    final isListening = normalized == 'listening';
    final isIdle = normalized == 'done' ||
        normalized == 'notlistening' ||
        normalized == 'not listening';

    setState(() {
      _isListening = isListening;
      if (isListening) {
        _voiceFeedback = 'Listening... say a short command.';
      } else if (isIdle && _taskController.text.trim().isEmpty) {
        _voiceFeedback = _speechReady
            ? 'Voice ready. Tap the mic and speak a short command.'
            : 'Voice input is unavailable on this machine.';
      }
    });

    if (isIdle) {
      _submitVoiceCommandIfReady();
    }
  }

  void _handleSpeechError(SpeechRecognitionError error) {
    if (!mounted) {
      return;
    }

    setState(() {
      _isListening = false;
      _queuedVoiceSubmit = false;
      if (error.permanent) {
        _speechReady = false;
      }
      _voiceFeedback = 'Voice input error: ${error.errorMsg}';
    });

    _appendEvent(
      OscarFeedEvent.system('Voice input error: ${error.errorMsg}', isError: true),
    );
  }

  void _handleSpeechResult(SpeechRecognitionResult result) {
    final transcript = result.recognizedWords.trim();
    if (!mounted || transcript.isEmpty) {
      return;
    }

    _taskController.value = TextEditingValue(
      text: transcript,
      selection: TextSelection.collapsed(offset: transcript.length),
    );

    setState(() {
      _voiceFeedback = result.finalResult
          ? 'Voice command captured.'
          : 'Listening... say a short command.';
      if (result.finalResult) {
        _queuedVoiceSubmit = true;
      }
    });

    if (result.finalResult) {
      _submitVoiceCommandIfReady();
    }
  }

  Future<void> _toggleListening() async {
    if (_isListening) {
      await _speech.stop();
      if (!mounted) {
        return;
      }
      setState(() {
        _isListening = false;
      });
      _submitVoiceCommandIfReady();
      return;
    }

    if (_isRunning) {
      return;
    }

    if (!_speechReady) {
      await _initSpeech(announceFailure: true);
      if (!_speechReady) {
        return;
      }
    }

    if (_socketStatus != SocketStatus.connected) {
      _appendEvent(
        OscarFeedEvent.system(
          'Connect to OSCAR before using voice commands.',
          isError: true,
        ),
      );
      return;
    }

    _taskController.clear();
    setState(() {
      _queuedVoiceSubmit = false;
      _voiceFeedback = 'Listening... say a short command.';
    });

    await _speech.listen(
      onResult: _handleSpeechResult,
      listenFor: const Duration(seconds: 18),
      pauseFor: const Duration(seconds: 2),
      listenOptions: stt.SpeechListenOptions(
        partialResults: true,
        cancelOnError: true,
      ),
    );

    if (!mounted) {
      return;
    }

    setState(() {
      _isListening = true;
    });
  }

  void _submitVoiceCommandIfReady() {
    if (!_queuedVoiceSubmit ||
        _isRunning ||
        _socketStatus != SocketStatus.connected ||
        _taskController.text.trim().isEmpty) {
      return;
    }

    _queuedVoiceSubmit = false;
    _sendTask(origin: 'voice');
  }

  void _setSocketStatus(SocketStatus status) {
    if (!mounted) {
      return;
    }
    setState(() => _socketStatus = status);
  }

  void _handleMessage(dynamic rawMessage) {
    try {
      final decoded = jsonDecode(rawMessage as String);
      if (decoded is! Map<String, dynamic>) {
        _appendEvent(OscarFeedEvent.system('Ignored non-object WebSocket message.'));
        return;
      }
      final event = OscarFeedEvent(decoded);
      _appendEvent(event);

      final type = event.type;
      if (type == 'task_accepted' || type == 'task_started') {
        setState(() => _isRunning = true);
      }
      if (type == 'task_completed' ||
          type == 'task_failed' ||
          type == 'task_cancelled' ||
          type == 'task_finalized' ||
          type == 'server_outcome' ||
          type == 'server_error') {
        setState(() => _isRunning = false);
      }
    } catch (error) {
      _appendEvent(OscarFeedEvent.system('Could not parse message: $error', isError: true));
    }
  }

  void _appendEvent(OscarFeedEvent event) {
    if (!mounted) {
      return;
    }
    setState(() => _events.add(event));
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!_scrollController.hasClients) {
        return;
      }
      _scrollController.animateTo(
        _scrollController.position.maxScrollExtent,
        duration: const Duration(milliseconds: 220),
        curve: Curves.easeOutCubic,
      );
    });
  }

  void _sendTask({String origin = 'text'}) {
    final task = _taskController.text.trim();
    final socket = _socket;
    if (task.isEmpty || socket == null || socket.readyState != WebSocket.open) {
      return;
    }

    socket.add(jsonEncode(<String, String>{
      'type': 'start_task',
      'prompt': task,
    }));
    _taskController.clear();
    setState(() {
      _isRunning = true;
      _queuedVoiceSubmit = false;
      if (_speechReady) {
        _voiceFeedback = origin == 'voice'
            ? 'Voice command sent.'
            : 'Voice ready. Tap the mic and speak a short command.';
      }
    });
    _appendEvent(
      OscarFeedEvent.system(
        origin == 'voice' ? 'Voice command submitted: $task' : 'Task submitted: $task',
      ),
    );
  }

  String get _voiceStatusText {
    if (_isListening) {
      return 'Listening... say a short command.';
    }
    if (!_speechReady) {
      return _voiceFeedback;
    }
    if (_isRunning) {
      return 'Voice command is paused while OSCAR is executing.';
    }
    if (_socketStatus != SocketStatus.connected) {
      return 'Connect to OSCAR to use voice commands.';
    }
    return _voiceFeedback;
  }

  @override
  Widget build(BuildContext context) {
    final canExecute = _socketStatus == SocketStatus.connected && !_isRunning;
    final canUseVoice =
        (_socketStatus == SocketStatus.connected && !_isRunning) || _isListening;

    return Scaffold(
      body: SafeArea(
        child: Column(
          children: <Widget>[
            _Header(status: _socketStatus, endpoint: _endpoint.toString()),
            Expanded(
              child: _events.isEmpty
                  ? const _EmptyState()
                  : ListView.builder(
                      controller: _scrollController,
                      padding: const EdgeInsets.fromLTRB(20, 8, 20, 20),
                      itemCount: _events.length,
                      itemBuilder: (context, index) {
                        return _EventCard(event: _events[index]);
                      },
                    ),
            ),
            _Composer(
              controller: _taskController,
              enabled: canExecute,
              running: _isRunning,
              listening: _isListening,
              voiceEnabled: canUseVoice,
              voiceStatus: _voiceStatusText,
              onSubmit: () => _sendTask(),
              onVoicePressed: _toggleListening,
            ),
          ],
        ),
      ),
    );
  }
}

class OscarFeedEvent {
  OscarFeedEvent(this.payload);

  factory OscarFeedEvent.system(String message, {bool isError = false}) {
    return OscarFeedEvent(<String, dynamic>{
      'type': isError ? 'client_error' : 'client_info',
      'status': isError ? 'error' : 'info',
      'message': message,
      'timestamp': DateTime.now().toUtc().toIso8601String(),
    });
  }

  final Map<String, dynamic> payload;

  String get type => _stringValue(payload['type'], fallback: 'event');
  String get status => _stringValue(payload['status'], fallback: '');
  String get message => _stringValue(payload['message'], fallback: '');
  String get action => _stringValue(payload['action'] ?? payload['payload']?['action'], fallback: '');
  String get route => _stringValue(payload['route'], fallback: '');
  String get reasoning => _stringValue(
        payload['reasoning'] ?? payload['final_message'] ?? payload['error'],
        fallback: '',
      );
  String get failureReason => _stringValue(payload['failure_reason'] ?? payload['error'], fallback: '');

  int? get step {
    final value = payload['step'];
    if (value is int) {
      return value;
    }
    if (value is num) {
      return value.toInt();
    }
    return int.tryParse(value?.toString() ?? '');
  }

  bool? get success {
    final value = payload['success'];
    if (value is bool) {
      return value;
    }
    final normalized = status.toLowerCase();
    if (<String>{'succeeded', 'completed', 'connected', 'running'}.contains(normalized)) {
      return true;
    }
    if (<String>{'failed', 'error', 'cancelled'}.contains(normalized)) {
      return false;
    }
    return null;
  }

  static String _stringValue(dynamic value, {required String fallback}) {
    if (value == null) {
      return fallback;
    }
    return value.toString().trim();
  }
}

class _Header extends StatelessWidget {
  const _Header({required this.status, required this.endpoint});

  final SocketStatus status;
  final String endpoint;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(22, 18, 22, 14),
      decoration: const BoxDecoration(
        border: Border(bottom: BorderSide(color: Color(0xFF2B2F37))),
      ),
      child: Row(
        children: <Widget>[
          const Text(
            'O.S.C.A.R.',
            style: TextStyle(
              fontSize: 24,
              fontWeight: FontWeight.w700,
              letterSpacing: 0,
            ),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Text(
              endpoint,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(color: Colors.white.withValues(alpha: 0.56)),
            ),
          ),
          _ConnectionPill(status: status),
        ],
      ),
    );
  }
}

class _ConnectionPill extends StatelessWidget {
  const _ConnectionPill({required this.status});

  final SocketStatus status;

  @override
  Widget build(BuildContext context) {
    final color = switch (status) {
      SocketStatus.connected => const Color(0xFF29D3A6),
      SocketStatus.connecting => const Color(0xFFFFC857),
      SocketStatus.disconnected => const Color(0xFFFF5C7A),
    };
    final label = switch (status) {
      SocketStatus.connected => 'Connected',
      SocketStatus.connecting => 'Connecting',
      SocketStatus.disconnected => 'Disconnected',
    };

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
      decoration: BoxDecoration(
        color: const Color(0xFF1C2026),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: const Color(0xFF343842)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          Container(
            width: 8,
            height: 8,
            decoration: BoxDecoration(color: color, shape: BoxShape.circle),
          ),
          const SizedBox(width: 8),
          Text(label, style: const TextStyle(fontWeight: FontWeight.w600)),
        ],
      ),
    );
  }
}

class _EmptyState extends StatelessWidget {
  const _EmptyState();

  @override
  Widget build(BuildContext context) {
    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 560),
        child: Text(
          'Send a task to start streaming OSCAR reasoning, actions, and execution results.',
          textAlign: TextAlign.center,
          style: TextStyle(
            color: Colors.white.withValues(alpha: 0.62),
            fontSize: 17,
            height: 1.4,
          ),
        ),
      ),
    );
  }
}

class _EventCard extends StatelessWidget {
  const _EventCard({required this.event});

  final OscarFeedEvent event;

  @override
  Widget build(BuildContext context) {
    final success = event.success;
    final action = event.action;
    final reasoning = event.reasoning;
    final failure = event.failureReason;
    final route = event.route;

    return Container(
      margin: const EdgeInsets.symmetric(vertical: 7),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFF181A1F),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: const Color(0xFF2D323B)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              Expanded(
                child: Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: <Widget>[
                    Text(
                      event.step == null ? event.type : 'Step ${event.step} · ${event.type}',
                      style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15),
                    ),
                    if (action.isNotEmpty) _ActionChip(label: action),
                    if (route.isNotEmpty) _MetaChip(label: route),
                  ],
                ),
              ),
              if (success != null) _StatusBadge(success: success, status: event.status),
            ],
          ),
          if (event.message.isNotEmpty) ...<Widget>[
            const SizedBox(height: 10),
            Text(
              event.message,
              style: TextStyle(color: Colors.white.withValues(alpha: 0.74)),
            ),
          ],
          if (reasoning.isNotEmpty) ...<Widget>[
            const SizedBox(height: 12),
            Text(
              reasoning,
              style: TextStyle(
                color: Colors.white.withValues(alpha: 0.82),
                fontStyle: FontStyle.italic,
                height: 1.35,
              ),
            ),
          ],
          if (failure.isNotEmpty && failure != reasoning) ...<Widget>[
            const SizedBox(height: 10),
            Text(
              failure,
              style: const TextStyle(color: Color(0xFFFF8CA0), height: 1.35),
            ),
          ],
          _EventMetrics(payload: event.payload),
        ],
      ),
    );
  }
}

class _ActionChip extends StatelessWidget {
  const _ActionChip({required this.label});

  final String label;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
      decoration: BoxDecoration(
        color: const Color(0xFF102D27),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: const Color(0xFF29D3A6)),
      ),
      child: Text(
        label,
        style: const TextStyle(
          color: Color(0xFF8EF1D5),
          fontFamily: 'monospace',
          fontWeight: FontWeight.w700,
        ),
      ),
    );
  }
}

class _MetaChip extends StatelessWidget {
  const _MetaChip({required this.label});

  final String label;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
      decoration: BoxDecoration(
        color: const Color(0xFF242832),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Text(label, style: TextStyle(color: Colors.white.withValues(alpha: 0.72))),
    );
  }
}

class _StatusBadge extends StatelessWidget {
  const _StatusBadge({required this.success, required this.status});

  final bool success;
  final String status;

  @override
  Widget build(BuildContext context) {
    final color = success ? const Color(0xFF29D3A6) : const Color(0xFFFF5C7A);
    final label = status.isEmpty ? (success ? 'success' : 'failed') : status;

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 6),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.13),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: color.withValues(alpha: 0.68)),
      ),
      child: Text(
        label,
        style: TextStyle(color: color, fontWeight: FontWeight.w700),
      ),
    );
  }
}

class _EventMetrics extends StatelessWidget {
  const _EventMetrics({required this.payload});

  final Map<String, dynamic> payload;

  @override
  Widget build(BuildContext context) {
    final attempts = payload['attempts'];
    final duration = payload['duration_ms'] ?? payload['result']?['duration_ms'];
    final strategy = payload['strategy'];
    final parts = <String>[
      if (attempts != null) 'attempts: $attempts',
      if (duration != null) 'duration: ${duration}ms',
      if (strategy != null && strategy.toString().trim().isNotEmpty) 'strategy: $strategy',
    ];

    if (parts.isEmpty) {
      return const SizedBox.shrink();
    }

    return Padding(
      padding: const EdgeInsets.only(top: 10),
      child: Text(
        parts.join('   '),
        style: TextStyle(
          color: Colors.white.withValues(alpha: 0.48),
          fontSize: 12,
          fontFamily: 'monospace',
        ),
      ),
    );
  }
}

class _Composer extends StatelessWidget {
  const _Composer({
    required this.controller,
    required this.enabled,
    required this.running,
    required this.listening,
    required this.voiceEnabled,
    required this.voiceStatus,
    required this.onSubmit,
    required this.onVoicePressed,
  });

  final TextEditingController controller;
  final bool enabled;
  final bool running;
  final bool listening;
  final bool voiceEnabled;
  final String voiceStatus;
  final VoidCallback onSubmit;
  final Future<void> Function() onVoicePressed;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(18, 14, 18, 18),
      decoration: const BoxDecoration(
        color: Color(0xFF14161A),
        border: Border(top: BorderSide(color: Color(0xFF2B2F37))),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              Expanded(
                child: TextField(
                  controller: controller,
                  enabled: enabled,
                  minLines: 1,
                  maxLines: 4,
                  textInputAction: TextInputAction.send,
                  onSubmitted: (_) {
                    if (enabled) {
                      onSubmit();
                    }
                  },
                  decoration: InputDecoration(
                    hintText: running
                        ? 'OSCAR is executing...'
                        : 'Ask OSCAR to do something on this PC',
                  ),
                ),
              ),
              const SizedBox(width: 12),
              Tooltip(
                message: listening ? 'Stop listening' : 'Speak a command',
                child: SizedBox(
                  width: 52,
                  height: 52,
                  child: FilledButton(
                    onPressed: voiceEnabled ? onVoicePressed : null,
                    style: FilledButton.styleFrom(
                      backgroundColor: listening
                          ? const Color(0xFF29D3A6)
                          : const Color(0xFF20232A),
                      foregroundColor: listening
                          ? const Color(0xFF071411)
                          : Colors.white.withValues(alpha: 0.82),
                      disabledBackgroundColor: const Color(0xFF30343B),
                      disabledForegroundColor: Colors.white.withValues(alpha: 0.34),
                      padding: EdgeInsets.zero,
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
                    ),
                    child: Icon(listening ? Icons.stop_rounded : Icons.mic_none_rounded),
                  ),
                ),
              ),
              const SizedBox(width: 12),
              SizedBox(
                height: 52,
                child: FilledButton(
                  onPressed: enabled ? onSubmit : null,
                  style: FilledButton.styleFrom(
                    backgroundColor: const Color(0xFF29D3A6),
                    foregroundColor: const Color(0xFF071411),
                    disabledBackgroundColor: const Color(0xFF30343B),
                    disabledForegroundColor: Colors.white.withValues(alpha: 0.38),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
                    padding: const EdgeInsets.symmetric(horizontal: 22),
                  ),
                  child: Text(running ? 'Running' : 'Execute'),
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          Text(
            voiceStatus,
            style: TextStyle(
              color: listening
                  ? const Color(0xFF8EF1D5)
                  : Colors.white.withValues(alpha: 0.62),
              fontSize: 12,
            ),
          ),
        ],
      ),
    );
  }
}

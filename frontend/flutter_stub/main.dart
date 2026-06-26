// Minimal Flutter UI stub showing how to call the API.
import 'package:flutter/material.dart';
import 'dart:convert';
import 'package:http/http.dart' as http;

void main() => runApp(const TNVedApp());

class TNVedApp extends StatelessWidget {
  const TNVedApp({super.key});
  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'TN VED Pro',
      home: const ClassifierPage(),
    );
  }
}

class ClassifierPage extends StatefulWidget {
  const ClassifierPage({super.key});
  @override
  State<ClassifierPage> createState() => _ClassifierPageState();
}

class _ClassifierPageState extends State<ClassifierPage> {
  final _controller = TextEditingController();
  String _result = '';

  Future<void> classify(String text) async {
    final uri = Uri.parse('http://localhost:8000/classify');
    final resp = await http.post(
      uri,
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'text': text}),
    );
    setState(() => _result = resp.body);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Классификация ТН ВЭД')),
      body: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          children: [
            TextField(
              controller: _controller,
              decoration: const InputDecoration(
                  labelText: 'Описание товара', border: OutlineInputBorder()),
              minLines: 3, maxLines: 6,
            ),
            const SizedBox(height: 12),
            ElevatedButton(
              onPressed: () => classify(_controller.text),
              child: const Text('Классифицировать'),
            ),
            const SizedBox(height: 12),
            Expanded(child: SingleChildScrollView(child: Text(_result))),
          ],
        ),
      ),
    );
  }
}

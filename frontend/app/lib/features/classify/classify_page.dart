import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lucide_icons/lucide_icons.dart';
import 'package:image_picker/image_picker.dart';
import 'dart:io';
import 'dart:convert';
import '../../core/theme/app_theme.dart';
import '../../core/constants/app_constants.dart';
import '../../core/services/api_service.dart';
import '../../shared/models/classification.dart';
import '../../shared/widgets/animated_card.dart';
import '../../shared/widgets/classification_result_card.dart';
import '../../shared/widgets/hint_chips.dart';

class ClassifyPage extends ConsumerStatefulWidget {
  const ClassifyPage({super.key});

  @override
  ConsumerState<ClassifyPage> createState() => _ClassifyPageState();
}

class _ClassifyPageState extends ConsumerState<ClassifyPage> {
  final _textController = TextEditingController();
  final _formKey = GlobalKey<FormState>();
  
  File? _selectedImage;
  String? _imageBase64;
  List<String> _selectedHints = [];
  ClassificationResult? _result;
  bool _isLoading = false;

  @override
  void dispose() {
    _textController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Классификация товара'),
        actions: [
          if (_result != null)
            IconButton(
              icon: const Icon(LucideIcons.save),
              onPressed: _saveToAudit,
            ),
        ],
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(AppConstants.defaultPadding),
        child: Form(
          key: _formKey,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // Description Input
              _buildDescriptionSection(),
              
              const SizedBox(height: AppConstants.largePadding),
              
              // Image Upload
              _buildImageSection(),
              
              const SizedBox(height: AppConstants.largePadding),
              
              // Hints
              _buildHintsSection(),
              
              const SizedBox(height: AppConstants.largePadding),
              
              // Classify Button
              _buildClassifyButton(),
              
              const SizedBox(height: AppConstants.largePadding),
              
              // Result
              if (_result != null) _buildResultSection(),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildDescriptionSection() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'Описание товара',
          style: Theme.of(context).textTheme.titleLarge?.copyWith(
            color: AppTheme.darkText,
            fontWeight: FontWeight.w600,
          ),
        ),
        const SizedBox(height: 8),
        TextFormField(
          controller: _textController,
          maxLines: 4,
          decoration: const InputDecoration(
            hintText: 'Введите подробное описание товара...',
            border: OutlineInputBorder(),
          ),
          validator: (value) {
            if (value == null || value.trim().isEmpty) {
              return 'Введите описание товара';
            }
            return null;
          },
        ),
      ],
    );
  }

  Widget _buildImageSection() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'Изображение товара',
          style: Theme.of(context).textTheme.titleLarge?.copyWith(
            color: AppTheme.darkText,
            fontWeight: FontWeight.w600,
          ),
        ),
        const SizedBox(height: 8),
        Row(
          children: [
            Expanded(
              child: AnimatedCard(
                onTap: _pickImage,
                child: Container(
                  height: 120,
                  decoration: BoxDecoration(
                    color: AppTheme.darkCard,
                    borderRadius: BorderRadius.circular(AppConstants.defaultRadius),
                    border: Border.all(
                      color: AppTheme.darkBorder,
                      width: 2,
                      style: BorderStyle.solid,
                    ),
                  ),
                  child: _selectedImage != null
                      ? ClipRRect(
                          borderRadius: BorderRadius.circular(AppConstants.defaultRadius),
                          child: Image.file(
                            _selectedImage!,
                            fit: BoxFit.cover,
                            width: double.infinity,
                            height: double.infinity,
                          ),
                        )
                      : Column(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            Icon(
                              LucideIcons.image,
                              color: AppTheme.darkTextSecondary,
                              size: 32,
                            ),
                            const SizedBox(height: 8),
                            Text(
                              'Нажмите для выбора изображения',
                              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                                color: AppTheme.darkTextSecondary,
                              ),
                            ),
                          ],
                        ),
                ),
              ),
            ),
            if (_selectedImage != null) ...[
              const SizedBox(width: 12),
              IconButton(
                onPressed: _removeImage,
                icon: const Icon(LucideIcons.x),
                style: IconButton.styleFrom(
                  backgroundColor: AppTheme.error.withOpacity(0.1),
                  foregroundColor: AppTheme.error,
                ),
              ),
            ],
          ],
        ),
      ],
    );
  }

  Widget _buildHintsSection() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'Подсказки',
          style: Theme.of(context).textTheme.titleLarge?.copyWith(
            color: AppTheme.darkText,
            fontWeight: FontWeight.w600,
          ),
        ),
        const SizedBox(height: 8),
        Text(
          'Выберите подходящие характеристики товара:',
          style: Theme.of(context).textTheme.bodyMedium?.copyWith(
            color: AppTheme.darkTextSecondary,
          ),
        ),
        const SizedBox(height: 12),
        HintChips(
          selectedHints: _selectedHints,
          onSelectionChanged: (hints) {
            setState(() {
              _selectedHints = hints;
            });
          },
        ),
      ],
    );
  }

  Widget _buildClassifyButton() {
    return SizedBox(
      width: double.infinity,
      child: ElevatedButton.icon(
        onPressed: _isLoading ? null : _classify,
        icon: _isLoading
            ? const SizedBox(
                width: 20,
                height: 20,
                child: CircularProgressIndicator(
                  strokeWidth: 2,
                  valueColor: AlwaysStoppedAnimation<Color>(Colors.white),
                ),
              )
            : const Icon(LucideIcons.search),
        label: Text(_isLoading ? 'Классификация...' : 'Классифицировать'),
        style: ElevatedButton.styleFrom(
          padding: const EdgeInsets.symmetric(vertical: 16),
        ),
      ),
    );
  }

  Widget _buildResultSection() {
    return ClassificationResultCard(
      result: _result!,
      onSave: _saveToAudit,
    );
  }

  Future<void> _pickImage() async {
    final picker = ImagePicker();
    final image = await picker.pickImage(
      source: ImageSource.gallery,
      maxWidth: 1024,
      maxHeight: 1024,
      imageQuality: 80,
    );

    if (image != null) {
      setState(() {
        _selectedImage = File(image.path);
      });
      
      // Convert to base64
      final bytes = await _selectedImage!.readAsBytes();
      _imageBase64 = base64Encode(bytes);
    }
  }

  void _removeImage() {
    setState(() {
      _selectedImage = null;
      _imageBase64 = null;
    });
  }

  Future<void> _classify() async {
    if (!_formKey.currentState!.validate()) return;

    setState(() {
      _isLoading = true;
    });

    try {
      final apiService = ref.read(apiServiceProvider);
      final result = await apiService.classify(
        text: _textController.text.trim(),
        imageBase64: _imageBase64,
        hints: _selectedHints.isNotEmpty ? _selectedHints : null,
      );

      setState(() {
        _result = ClassificationResult.fromJson(result);
        _isLoading = false;
      });

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Классификация завершена с уверенностью ${(_result!.confidence * 100).toStringAsFixed(1)}%'),
            backgroundColor: AppTheme.success,
          ),
        );
      }
    } catch (e) {
      setState(() {
        _isLoading = false;
      });

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Ошибка классификации: $e'),
            backgroundColor: AppTheme.error,
          ),
        );
      }
    }
  }

  Future<void> _saveToAudit() async {
    if (_result == null) return;

    try {
      final apiService = ref.read(apiServiceProvider);
      await apiService.saveToAudit(
        hsCode: _result!.hsCode,
        description: _textController.text.trim(),
        confidence: _result!.confidence,
        rationale: _result!.rationale,
      );

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Результат сохранен в аудит'),
            backgroundColor: AppTheme.success,
          ),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Ошибка сохранения: $e'),
            backgroundColor: AppTheme.error,
          ),
        );
      }
    }
  }
}

















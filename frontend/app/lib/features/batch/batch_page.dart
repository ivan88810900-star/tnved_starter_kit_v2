import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lucide_icons/lucide_icons.dart';
import 'package:file_picker/file_picker.dart';
import 'dart:io';
import '../../core/theme/app_theme.dart';
import '../../core/constants/app_constants.dart';
import '../../core/services/api_service.dart';
import '../../shared/widgets/animated_card.dart';

class BatchPage extends ConsumerStatefulWidget {
  const BatchPage({super.key});

  @override
  ConsumerState<BatchPage> createState() => _BatchPageState();
}

class _BatchPageState extends ConsumerState<BatchPage> {
  File? _selectedFile;
  bool _isProcessing = false;
  String? _downloadUrl;
  double _progress = 0.0;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Пакетная обработка'),
        actions: [
          if (_downloadUrl != null)
            IconButton(
              icon: const Icon(LucideIcons.download),
              onPressed: _downloadResult,
            ),
        ],
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(AppConstants.defaultPadding),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Instructions
            _buildInstructionsSection(),
            
            const SizedBox(height: AppConstants.largePadding),
            
            // File Selection
            _buildFileSelectionSection(),
            
            const SizedBox(height: AppConstants.largePadding),
            
            // Progress
            if (_isProcessing) _buildProgressSection(),
            
            const SizedBox(height: AppConstants.largePadding),
            
            // Process Button
            _buildProcessButton(),
            
            const SizedBox(height: AppConstants.largePadding),
            
            // Result
            if (_downloadUrl != null) _buildResultSection(),
          ],
        ),
      ),
    );
  }

  Widget _buildInstructionsSection() {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(AppConstants.defaultPadding),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Icon(
                  LucideIcons.info,
                  color: AppTheme.info,
                  size: 24,
                ),
                const SizedBox(width: 12),
                Text(
                  'Инструкции',
                  style: Theme.of(context).textTheme.titleLarge?.copyWith(
                    color: AppTheme.darkText,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            Text(
              '1. Подготовьте Excel файл с колонками:',
              style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                color: AppTheme.darkText,
                fontWeight: FontWeight.w600,
              ),
            ),
            const SizedBox(height: 8),
            _buildInstructionItem('A - ID товара (уникальный идентификатор)'),
            _buildInstructionItem('B - Описание товара'),
            _buildInstructionItem('C - Дополнительные характеристики (опционально)'),
            const SizedBox(height: 12),
            Text(
              '2. Максимальный размер файла: ${AppConstants.maxExcelSizeMB} МБ',
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                color: AppTheme.darkTextSecondary,
              ),
            ),
            Text(
              '3. Максимальное количество товаров: ${AppConstants.maxBatchItems}',
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                color: AppTheme.darkTextSecondary,
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildInstructionItem(String text) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 4,
            height: 4,
            margin: const EdgeInsets.only(top: 8, right: 8),
            decoration: const BoxDecoration(
              color: AppTheme.info,
              shape: BoxShape.circle,
            ),
          ),
          Expanded(
            child: Text(
              text,
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                color: AppTheme.darkTextSecondary,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildFileSelectionSection() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'Выберите Excel файл',
          style: Theme.of(context).textTheme.titleLarge?.copyWith(
            color: AppTheme.darkText,
            fontWeight: FontWeight.w600,
          ),
        ),
        const SizedBox(height: 12),
        AnimatedCard(
          onTap: _selectFile,
          child: Container(
            height: 120,
            decoration: BoxDecoration(
              color: AppTheme.darkCard,
              borderRadius: BorderRadius.circular(AppConstants.defaultRadius),
              border: Border.all(
                color: _selectedFile != null ? AppTheme.primaryBlue : AppTheme.darkBorder,
                width: 2,
                style: BorderStyle.solid,
              ),
            ),
            child: _selectedFile != null
                ? Padding(
                    padding: const EdgeInsets.all(AppConstants.defaultPadding),
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        const Icon(
                          LucideIcons.fileSpreadsheet,
                          color: AppTheme.primaryBlue,
                          size: 32,
                        ),
                        const SizedBox(height: 8),
                        Text(
                          _selectedFile!.path.split('/').last,
                          style: Theme.of(context).textTheme.titleMedium?.copyWith(
                            color: AppTheme.darkText,
                            fontWeight: FontWeight.w600,
                          ),
                          textAlign: TextAlign.center,
                        ),
                        Text(
                          '${(_selectedFile!.lengthSync() / 1024 / 1024).toStringAsFixed(1)} МБ',
                          style: Theme.of(context).textTheme.bodySmall?.copyWith(
                            color: AppTheme.darkTextSecondary,
                          ),
                        ),
                      ],
                    ),
                  )
                : Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Icon(
                        LucideIcons.upload,
                        color: AppTheme.darkTextSecondary,
                        size: 32,
                      ),
                      const SizedBox(height: 8),
                      Text(
                        'Нажмите для выбора файла',
                        style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                          color: AppTheme.darkTextSecondary,
                        ),
                      ),
                      Text(
                        'Поддерживаемые форматы: XLSX, XLS',
                        style: Theme.of(context).textTheme.bodySmall?.copyWith(
                          color: AppTheme.darkTextTertiary,
                        ),
                      ),
                    ],
                  ),
          ),
        ),
        if (_selectedFile != null) ...[
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: _selectFile,
                  icon: const Icon(LucideIcons.refreshCw),
                  label: const Text('Выбрать другой файл'),
                ),
              ),
              const SizedBox(width: 12),
              IconButton(
                onPressed: _removeFile,
                icon: const Icon(LucideIcons.x),
                style: IconButton.styleFrom(
                  backgroundColor: AppTheme.error.withOpacity(0.1),
                  foregroundColor: AppTheme.error,
                ),
              ),
            ],
          ),
        ],
      ],
    );
  }

  Widget _buildProgressSection() {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(AppConstants.defaultPadding),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Icon(
                  LucideIcons.loader,
                  color: AppTheme.primaryBlue,
                  size: 24,
                ),
                const SizedBox(width: 12),
                Text(
                  'Обработка файла',
                  style: Theme.of(context).textTheme.titleLarge?.copyWith(
                    color: AppTheme.darkText,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 16),
            LinearProgressIndicator(
              value: _progress,
              backgroundColor: AppTheme.darkBorder,
              valueColor: const AlwaysStoppedAnimation<Color>(AppTheme.primaryBlue),
            ),
            const SizedBox(height: 8),
            Text(
              '${(_progress * 100).toStringAsFixed(0)}%',
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                color: AppTheme.darkTextSecondary,
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildProcessButton() {
    return SizedBox(
      width: double.infinity,
      child: ElevatedButton.icon(
        onPressed: _selectedFile != null && !_isProcessing ? _processFile : null,
        icon: _isProcessing
            ? const SizedBox(
                width: 20,
                height: 20,
                child: CircularProgressIndicator(
                  strokeWidth: 2,
                  valueColor: AlwaysStoppedAnimation<Color>(Colors.white),
                ),
              )
            : const Icon(LucideIcons.play),
        label: Text(_isProcessing ? 'Обработка...' : 'Начать обработку'),
        style: ElevatedButton.styleFrom(
          padding: const EdgeInsets.symmetric(vertical: 16),
        ),
      ),
    );
  }

  Widget _buildResultSection() {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(AppConstants.defaultPadding),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Icon(
                  LucideIcons.checkCircle,
                  color: AppTheme.success,
                  size: 24,
                ),
                const SizedBox(width: 12),
                Text(
                  'Обработка завершена',
                  style: Theme.of(context).textTheme.titleLarge?.copyWith(
                    color: AppTheme.darkText,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 16),
            Text(
              'Результат готов к скачиванию. Файл содержит классификацию всех товаров с кодами ТН ВЭД и дополнительной информацией.',
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                color: AppTheme.darkTextSecondary,
              ),
            ),
            const SizedBox(height: 16),
            SizedBox(
              width: double.infinity,
              child: ElevatedButton.icon(
                onPressed: _downloadResult,
                icon: const Icon(LucideIcons.download),
                label: const Text('Скачать результат'),
                style: ElevatedButton.styleFrom(
                  backgroundColor: AppTheme.success,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _selectFile() async {
    try {
      final result = await FilePicker.platform.pickFiles(
        type: FileType.custom,
        allowedExtensions: AppConstants.supportedExcelFormats,
        allowMultiple: false,
      );

      if (result != null && result.files.single.path != null) {
        final file = File(result.files.single.path!);
        final fileSizeMB = file.lengthSync() / 1024 / 1024;

        if (fileSizeMB > AppConstants.maxExcelSizeMB) {
          if (mounted) {
            ScaffoldMessenger.of(context).showSnackBar(
              SnackBar(
                content: Text('Файл слишком большой. Максимальный размер: ${AppConstants.maxExcelSizeMB} МБ'),
                backgroundColor: AppTheme.error,
              ),
            );
          }
          return;
        }

        setState(() {
          _selectedFile = file;
          _downloadUrl = null;
        });
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Ошибка выбора файла: $e'),
            backgroundColor: AppTheme.error,
          ),
        );
      }
    }
  }

  void _removeFile() {
    setState(() {
      _selectedFile = null;
      _downloadUrl = null;
    });
  }

  Future<void> _processFile() async {
    if (_selectedFile == null) return;

    setState(() {
      _isProcessing = true;
      _progress = 0.0;
    });

    try {
      final apiService = ref.read(apiServiceProvider);
      
      // Simulate progress
      for (int i = 0; i <= 100; i += 10) {
        await Future.delayed(const Duration(milliseconds: 200));
        setState(() {
          _progress = i / 100;
        });
      }

      final result = await apiService.batchClassify(_selectedFile!.path);
      
      setState(() {
        _isProcessing = false;
        _downloadUrl = result['download_url'];
      });

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Обработка завершена успешно'),
            backgroundColor: AppTheme.success,
          ),
        );
      }
    } catch (e) {
      setState(() {
        _isProcessing = false;
      });

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Ошибка обработки: $e'),
            backgroundColor: AppTheme.error,
          ),
        );
      }
    }
  }

  Future<void> _downloadResult() async {
    if (_downloadUrl == null) return;

    try {
      // TODO: Implement actual download functionality
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Функция скачивания будет реализована'),
            backgroundColor: AppTheme.info,
          ),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Ошибка скачивания: $e'),
            backgroundColor: AppTheme.error,
          ),
        );
      }
    }
  }
}



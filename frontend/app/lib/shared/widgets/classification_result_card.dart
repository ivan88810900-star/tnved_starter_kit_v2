import 'package:flutter/material.dart';
import 'package:lucide_icons/lucide_icons.dart';
import '../../core/theme/app_theme.dart';
import '../../core/constants/app_constants.dart';
import '../../shared/models/classification.dart';

class ClassificationResultCard extends StatelessWidget {
  final ClassificationResult result;
  final VoidCallback? onSave;

  const ClassificationResultCard({
    super.key,
    required this.result,
    this.onSave,
  });

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(AppConstants.defaultPadding),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Header
            Row(
              children: [
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                  decoration: BoxDecoration(
                    color: _getConfidenceColor().withOpacity(0.1),
                    borderRadius: BorderRadius.circular(20),
                    border: Border.all(
                      color: _getConfidenceColor(),
                      width: 1,
                    ),
                  ),
                  child: Text(
                    'Уверенность: ${(result.confidence * 100).toStringAsFixed(1)}%',
                    style: Theme.of(context).textTheme.labelMedium?.copyWith(
                      color: _getConfidenceColor(),
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
                const Spacer(),
                if (result.validated == true)
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                    decoration: BoxDecoration(
                      color: AppTheme.success.withOpacity(0.1),
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        const Icon(
                          LucideIcons.checkCircle,
                          color: AppTheme.success,
                          size: 16,
                        ),
                        const SizedBox(width: 4),
                        Text(
                          'Проверен',
                          style: Theme.of(context).textTheme.labelSmall?.copyWith(
                            color: AppTheme.success,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                      ],
                    ),
                  ),
              ],
            ),
            
            const SizedBox(height: 16),
            
            // HS Code
            _buildHSCodeSection(context),
            
            const SizedBox(height: 16),
            
            // Rationale
            if (result.rationale.isNotEmpty) _buildRationaleSection(context),
            
            const SizedBox(height: 16),
            
            // Alternatives
            if (result.alternatives.isNotEmpty) _buildAlternativesSection(context),
            
            const SizedBox(height: 16),
            
            // Clarification Questions
            if (result.clarificationQuestions?.isNotEmpty == true)
              _buildClarificationSection(context),
            
            const SizedBox(height: 16),
            
            // Actions
            _buildActionsSection(context),
          ],
        ),
      ),
    );
  }

  Widget _buildHSCodeSection(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppTheme.primaryBlue.withOpacity(0.1),
        borderRadius: BorderRadius.circular(AppConstants.defaultRadius),
        border: Border.all(
          color: AppTheme.primaryBlue.withOpacity(0.3),
          width: 1,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(
                LucideIcons.hash,
                color: AppTheme.primaryBlue,
                size: 20,
              ),
              const SizedBox(width: 8),
              Text(
                'Код ТН ВЭД',
                style: Theme.of(context).textTheme.titleMedium?.copyWith(
                  color: AppTheme.primaryBlue,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            result.hsCode,
            style: Theme.of(context).textTheme.headlineMedium?.copyWith(
              color: AppTheme.darkText,
              fontWeight: FontWeight.w700,
              letterSpacing: 1.2,
            ),
          ),
          if (result.titleRu != null) ...[
            const SizedBox(height: 4),
            Text(
              result.titleRu!,
              style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                color: AppTheme.darkTextSecondary,
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildRationaleSection(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            const Icon(
              LucideIcons.lightbulb,
              color: AppTheme.gold,
              size: 20,
            ),
            const SizedBox(width: 8),
            Text(
              'Обоснование',
              style: Theme.of(context).textTheme.titleMedium?.copyWith(
                color: AppTheme.gold,
                fontWeight: FontWeight.w600,
              ),
            ),
          ],
        ),
        const SizedBox(height: 8),
        ...result.rationale.map((item) => Padding(
          padding: const EdgeInsets.only(bottom: 4),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                width: 4,
                height: 4,
                margin: const EdgeInsets.only(top: 8, right: 8),
                decoration: const BoxDecoration(
                  color: AppTheme.gold,
                  shape: BoxShape.circle,
                ),
              ),
              Expanded(
                child: Text(
                  item,
                  style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    color: AppTheme.darkTextSecondary,
                  ),
                ),
              ),
            ],
          ),
        )),
      ],
    );
  }

  Widget _buildAlternativesSection(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            const Icon(
              LucideIcons.list,
              color: AppTheme.info,
              size: 20,
            ),
            const SizedBox(width: 8),
            Text(
              'Альтернативные варианты',
              style: Theme.of(context).textTheme.titleMedium?.copyWith(
                color: AppTheme.info,
                fontWeight: FontWeight.w600,
              ),
            ),
          ],
        ),
        const SizedBox(height: 8),
        ...result.alternatives.map((alternative) => Container(
          margin: const EdgeInsets.only(bottom: 8),
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: AppTheme.darkCard,
            borderRadius: BorderRadius.circular(AppConstants.defaultRadius),
            border: Border.all(
              color: AppTheme.darkBorder,
              width: 1,
            ),
          ),
          child: Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      alternative.code,
                      style: Theme.of(context).textTheme.titleSmall?.copyWith(
                        color: AppTheme.darkText,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    Text(
                      alternative.titleRu,
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: AppTheme.darkTextSecondary,
                      ),
                    ),
                  ],
                ),
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                decoration: BoxDecoration(
                  color: AppTheme.info.withOpacity(0.1),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Text(
                  '${(alternative.confidence * 100).toStringAsFixed(0)}%',
                  style: Theme.of(context).textTheme.labelSmall?.copyWith(
                    color: AppTheme.info,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
            ],
          ),
        )),
      ],
    );
  }

  Widget _buildClarificationSection(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppTheme.warning.withOpacity(0.1),
        borderRadius: BorderRadius.circular(AppConstants.defaultRadius),
        border: Border.all(
          color: AppTheme.warning.withOpacity(0.3),
          width: 1,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(
                LucideIcons.helpCircle,
                color: AppTheme.warning,
                size: 20,
              ),
              const SizedBox(width: 8),
              Text(
                'Уточняющие вопросы',
                style: Theme.of(context).textTheme.titleMedium?.copyWith(
                  color: AppTheme.warning,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          ...result.clarificationQuestions!.map((question) => Padding(
            padding: const EdgeInsets.only(bottom: 4),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Container(
                  width: 4,
                  height: 4,
                  margin: const EdgeInsets.only(top: 8, right: 8),
                  decoration: const BoxDecoration(
                    color: AppTheme.warning,
                    shape: BoxShape.circle,
                  ),
                ),
                Expanded(
                  child: Text(
                    question,
                    style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                      color: AppTheme.darkTextSecondary,
                    ),
                  ),
                ),
              ],
            ),
          )),
        ],
      ),
    );
  }

  Widget _buildActionsSection(BuildContext context) {
    return Row(
      children: [
        Expanded(
          child: OutlinedButton.icon(
            onPressed: onSave,
            icon: const Icon(LucideIcons.save),
            label: const Text('Сохранить в аудит'),
          ),
        ),
        const SizedBox(width: 12),
        Expanded(
          child: OutlinedButton.icon(
            onPressed: () {
              // TODO: Implement share functionality
            },
            icon: const Icon(LucideIcons.share),
            label: const Text('Поделиться'),
          ),
        ),
      ],
    );
  }

  Color _getConfidenceColor() {
    if (result.confidence >= 0.8) return AppTheme.success;
    if (result.confidence >= 0.6) return AppTheme.warning;
    return AppTheme.error;
  }
}



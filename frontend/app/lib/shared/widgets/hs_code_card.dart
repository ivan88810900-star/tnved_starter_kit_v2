import 'package:flutter/material.dart';
import '../../core/theme/app_theme.dart';
import '../../core/constants/app_constants.dart';
import '../models/hs_code.dart';

class HSCodeCard extends StatelessWidget {
  final HSCode code;
  final bool isSelected;

  const HSCodeCard({
    super.key,
    required this.code,
    this.isSelected = false,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(AppConstants.defaultPadding),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Code
          Row(
            children: [
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                decoration: BoxDecoration(
                  color: isSelected ? AppTheme.primaryBlue : AppTheme.darkCard,
                  borderRadius: BorderRadius.circular(6),
                  border: Border.all(
                    color: isSelected ? AppTheme.primaryBlue : AppTheme.darkBorder,
                  ),
                ),
                child: Text(
                  code.code,
                  style: Theme.of(context).textTheme.titleSmall?.copyWith(
                    color: isSelected ? Colors.white : AppTheme.darkText,
                    fontWeight: FontWeight.w600,
                    letterSpacing: 0.5,
                  ),
                ),
              ),
              const Spacer(),
              if (isSelected)
                const Icon(
                  Icons.check_circle,
                  color: AppTheme.primaryBlue,
                  size: 20,
                ),
            ],
          ),
          
          const SizedBox(height: 8),
          
          // Title
          Text(
            code.titleRu,
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
              color: AppTheme.darkText,
              fontWeight: FontWeight.w500,
            ),
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
          ),
          
          // English title if available
          if (code.titleEn != null) ...[
            const SizedBox(height: 4),
            Text(
              code.titleEn!,
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                color: AppTheme.darkTextSecondary,
                fontStyle: FontStyle.italic,
              ),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
            ),
          ],
          
          // Hierarchy info
          if (code.chapter != null || code.heading != null || code.subheading != null) ...[
            const SizedBox(height: 8),
            Wrap(
              spacing: 4,
              runSpacing: 4,
              children: [
                if (code.chapter != null)
                  _buildHierarchyChip(context, 'Глава', code.chapter!),
                if (code.heading != null)
                  _buildHierarchyChip(context, 'Позиция', code.heading!),
                if (code.subheading != null)
                  _buildHierarchyChip(context, 'Подпозиция', code.subheading!),
              ],
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildHierarchyChip(BuildContext context, String label, String value) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
      decoration: BoxDecoration(
        color: AppTheme.darkCard,
        borderRadius: BorderRadius.circular(4),
        border: Border.all(color: AppTheme.darkBorder),
      ),
      child: Text(
        '$label: $value',
        style: Theme.of(context).textTheme.labelSmall?.copyWith(
          color: AppTheme.darkTextTertiary,
        ),
      ),
    );
  }
}



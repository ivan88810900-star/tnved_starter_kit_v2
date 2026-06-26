import 'package:flutter/material.dart';
import '../../core/theme/app_theme.dart';
import '../../core/constants/app_constants.dart';

class HintChips extends StatelessWidget {
  final List<String> selectedHints;
  final Function(List<String>) onSelectionChanged;

  const HintChips({
    super.key,
    required this.selectedHints,
    required this.onSelectionChanged,
  });

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: AppConstants.commonHints.map((hint) {
        final isSelected = selectedHints.contains(hint);
        
        return FilterChip(
          label: Text(hint),
          selected: isSelected,
          onSelected: (selected) {
            final newSelection = List<String>.from(selectedHints);
            if (selected) {
              newSelection.add(hint);
            } else {
              newSelection.remove(hint);
            }
            onSelectionChanged(newSelection);
          },
          selectedColor: AppTheme.primaryBlue.withOpacity(0.2),
          checkmarkColor: AppTheme.primaryBlue,
          labelStyle: TextStyle(
            color: isSelected ? AppTheme.primaryBlue : AppTheme.darkText,
            fontWeight: isSelected ? FontWeight.w600 : FontWeight.w400,
          ),
          side: BorderSide(
            color: isSelected ? AppTheme.primaryBlue : AppTheme.darkBorder,
            width: 1,
          ),
        );
      }).toList(),
    );
  }
}



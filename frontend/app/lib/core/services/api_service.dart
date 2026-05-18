import 'package:dio/dio.dart';
import 'package:dio_retry/dio_retry.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../constants/app_constants.dart';

class ApiService {
  late final Dio _dio;
  late final String _baseUrl;
  
  ApiService() {
    _initializeDio();
  }
  
  void _initializeDio() {
    _baseUrl = _getBaseUrl();
    
    _dio = Dio(BaseOptions(
      baseUrl: _baseUrl,
      connectTimeout: const Duration(seconds: 30),
      receiveTimeout: const Duration(seconds: 30),
      sendTimeout: const Duration(seconds: 30),
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      },
    ));
    
    // Добавляем retry interceptor
    _dio.interceptors.add(
      RetryInterceptor(
        dio: _dio,
        logPrint: print,
        retries: 3,
        retryDelays: const [
          Duration(seconds: 1),
          Duration(seconds: 2),
          Duration(seconds: 4),
        ],
      ),
    );
    
    // Добавляем logging interceptor для отладки
    _dio.interceptors.add(
      LogInterceptor(
        requestBody: true,
        responseBody: true,
        error: true,
      ),
    );
  }
  
  String _getBaseUrl() {
    // В реальном приложении здесь будет логика выбора окружения
    // Пока используем dev URL
    return AppConstants.devBaseUrl;
  }
  
  // Health Check
  Future<bool> checkHealth() async {
    try {
      final response = await _dio.get(AppConstants.healthEndpoint);
      return response.statusCode == 200;
    } catch (e) {
      return false;
    }
  }
  
  // Classification
  Future<Map<String, dynamic>> classify({
    String? text,
    String? imageBase64,
    List<String>? hints,
  }) async {
    final data = <String, dynamic>{};
    
    if (text != null && text.isNotEmpty) {
      data['text'] = text;
    }
    
    if (imageBase64 != null && imageBase64.isNotEmpty) {
      data['image_b64'] = imageBase64;
    }
    
    if (hints != null && hints.isNotEmpty) {
      data['hints'] = hints;
    }
    
    final response = await _dio.post(
      AppConstants.classifyEndpoint,
      data: data,
    );
    
    return response.data;
  }
  
  // Search Codes
  Future<List<Map<String, dynamic>>> searchCodes(String query) async {
    final response = await _dio.get(
      AppConstants.codesSearchEndpoint,
      queryParameters: {'q': query},
    );
    
    return List<Map<String, dynamic>>.from(response.data);
  }
  
  // Get Code Details
  Future<Map<String, dynamic>> getCodeDetails(String hsCode) async {
    final response = await _dio.get('${AppConstants.codesDetailEndpoint}/$hsCode');
    return response.data;
  }
  
  // Get Notes
  Future<Map<String, dynamic>> getNotes(String level, String id) async {
    final response = await _dio.get('${AppConstants.notesEndpoint}/$level/$id');
    return response.data;
  }
  
  // Get Data Sources
  Future<List<Map<String, dynamic>>> getDataSources() async {
    final response = await _dio.get(AppConstants.dataSourcesEndpoint);
    return List<Map<String, dynamic>>.from(response.data);
  }
  
  // Batch Classification
  Future<Map<String, dynamic>> batchClassify(String filePath) async {
    final formData = FormData.fromMap({
      'file': await MultipartFile.fromFile(filePath),
    });
    
    final response = await _dio.post(
      AppConstants.batchClassifyEndpoint,
      data: formData,
      options: Options(
        headers: {'Content-Type': 'multipart/form-data'},
      ),
    );
    
    return response.data;
  }
  
  // Get Audit Logs
  Future<List<Map<String, dynamic>>> getAuditLogs({
    int? limit,
    int? offset,
  }) async {
    final queryParams = <String, dynamic>{};
    
    if (limit != null) queryParams['limit'] = limit;
    if (offset != null) queryParams['offset'] = offset;
    
    final response = await _dio.get(
      AppConstants.auditLogsEndpoint,
      queryParameters: queryParams,
    );
    
    return List<Map<String, dynamic>>.from(response.data);
  }
  
  // Save to Audit
  Future<void> saveToAudit({
    required String hsCode,
    required String description,
    required double confidence,
    List<String>? rationale,
  }) async {
    final data = {
      'hs_code': hsCode,
      'description': description,
      'confidence': confidence,
      'rationale': rationale ?? [],
    };
    
    await _dio.post('/audit/save', data: data);
  }
}

// Provider для ApiService
final apiServiceProvider = Provider<ApiService>((ref) {
  return ApiService();
});

// Provider для проверки здоровья API
final healthCheckProvider = FutureProvider<bool>((ref) async {
  final apiService = ref.read(apiServiceProvider);
  return await apiService.checkHealth();
});



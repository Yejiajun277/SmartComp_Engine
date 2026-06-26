import { useState } from 'react';
import { Card, Form, Input, Select, Button, Tag, Space, Typography, Alert } from 'antd';
import { QuestionCircleOutlined, SendOutlined, ArrowLeftOutlined } from '@ant-design/icons';

const { Text, Paragraph } = Typography;
const { TextArea } = Input;

/**
 * 描述质量评估问题面板组件
 *
 * 当用户输入的产品描述不够详细时，展示LLM生成的补充问题，
 * 引导用户提供更多信息以提升竞品分析质量。
 *
 * Props:
 * - questions: [{question, field, options}] - LLM生成的问题列表
 * - missingDimensions: string[] - 缺失的维度
 * - qualityScore: number - 质量分数
 * - originalDescription: string - 原始描述
 * - onComplete(enrichedDescription: string, answers: [{field, answer}]) - 用户完成回答后的回调
 * - onSkip() - 用户跳过问题的回调
 * - onBack() - 返回修改描述的回调
 * - loading: boolean - 是否正在提交
 */
export default function DescriptionEvaluator({
  questions = [],
  missingDimensions = [],
  qualityScore = 0,
  originalDescription = '',
  onComplete,
  onSkip,
  onBack,
  loading = false,
}) {
  const [form] = Form.useForm();
  const [answeredCount, setAnsweredCount] = useState(0);

  const handleSubmit = (values) => {
    // 收集用户回答（带字段名）
    const answersList = [];
    // 合并原始描述和用户回答为富描述
    const textAnswers = [];

    questions.forEach((q, index) => {
      const answer = values[`question_${index}`];
      if (answer && answer.trim()) {
        answersList.push({ field: q.field, answer: answer.trim() });
        textAnswers.push(`- ${q.question.replace(/[？?]/, '')}：${answer.trim()}`);
      }
    });

    let enrichedDescription = originalDescription;
    if (textAnswers.length > 0) {
      enrichedDescription = `${originalDescription}\n\n补充信息：\n${textAnswers.join('\n')}`;
    }

    onComplete(enrichedDescription, answersList);
  };

  const handleValuesChange = (_, allValues) => {
    const count = questions.filter((_, index) => {
      const val = allValues[`question_${index}`];
      return val && val.trim();
    }).length;
    setAnsweredCount(count);
  };

  // 质量分数对应的颜色和提示
  const getScoreColor = (score) => {
    if (score >= 0.7) return 'success';
    if (score >= 0.5) return 'warning';
    return 'error';
  };

  const getScoreText = (score) => {
    if (score >= 0.7) return '良好';
    if (score >= 0.5) return '一般';
    return '不足';
  };

  return (
    <Card
      title={
        <Space>
          <QuestionCircleOutlined />
          <span>补充产品信息</span>
        </Space>
      }
      style={{ height: '100%' }}
      extra={
        <Tag color={getScoreColor(qualityScore)}>
          描述质量：{getScoreText(qualityScore)} ({Math.round(qualityScore * 100)}%)
        </Tag>
      }
    >
      <Alert
        message="描述信息不够详细"
        description={
          <span>
            为了生成更准确的竞品分析报告，建议补充以下信息：
            {missingDimensions.length > 0 && (
              <span style={{ marginLeft: 4 }}>
                {missingDimensions.map((dim, i) => (
                  <Tag key={i} color="orange" style={{ marginLeft: 4 }}>
                    {dim}
                  </Tag>
                ))}
              </span>
            )}
          </span>
        }
        type="warning"
        showIcon
        style={{ marginBottom: 16 }}
      />

      <Paragraph type="secondary" style={{ marginBottom: 16 }}>
        <Text strong>原始描述：</Text> {originalDescription}
      </Paragraph>

      <Form
        form={form}
        layout="vertical"
        onFinish={handleSubmit}
        onValuesChange={handleValuesChange}
      >
        {questions.map((q, index) => (
          <Form.Item
            key={index}
            name={`question_${index}`}
            label={
              <span>
                <Text strong>{q.question}</Text>
                {q.field && (
                  <Tag color="blue" style={{ marginLeft: 8 }}>
                    {getFieldLabel(q.field)}
                  </Tag>
                )}
              </span>
            }
          >
            {q.options && q.options.length > 0 ? (
              <Select
                placeholder="请选择..."
                allowClear
                options={q.options
                  .filter(opt => opt != null)
                  .map(opt => ({ label: opt, value: opt }))}
              />
            ) : (
              <TextArea
                placeholder="请输入..."
                autoSize={{ minRows: 2, maxRows: 4 }}
              />
            )}
          </Form.Item>
        ))}

        <Form.Item style={{ marginBottom: 0 }}>
          <Space style={{ width: '100%', justifyContent: 'space-between' }}>
            <Space>
              <Button
                icon={<ArrowLeftOutlined />}
                onClick={onBack}
                disabled={loading}
              >
                修改描述
              </Button>
              <Button
                type="link"
                onClick={onSkip}
                disabled={loading}
              >
                跳过，直接分析
              </Button>
            </Space>
            <Space>
              <Text type="secondary">
                已回答 {answeredCount}/{questions.length}
              </Text>
              <Button
                type="primary"
                htmlType="submit"
                icon={<SendOutlined />}
                loading={loading}
              >
                提交分析
              </Button>
            </Space>
          </Space>
        </Form.Item>
      </Form>
    </Card>
  );
}

/**
 * 获取字段的中文标签
 */
function getFieldLabel(field) {
  const labels = {
    product_name: '产品名称',
    category: '产品类别',
    features: '核心功能',
    target_users: '目标用户',
    differentiation: '差异化',
    general: '综合信息',
  };
  return labels[field] || field;
}
